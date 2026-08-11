"""
Video compression via ffmpeg CRF encoding.

CRF targets visual quality rather than a fixed bitrate — the encoder
allocates bits per frame adaptively, producing smaller files with no
perceptible quality loss.

The ffmpeg/ffprobe binaries are resolved from the FFMPEG_BINARY /
FFPROBE_BINARY environment variables when set, otherwise from PATH. That
makes the module portable across local Windows installs, Docker images and
Streamlit Community Cloud (where `packages.txt` installs ffmpeg via apt).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be located."""


CODEC_PRESETS = {
    "H.264": {
        "vcodec": "libx264",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "default_crf": 23,
        "crf_range": (18, 32),
        # Reference point for the size estimate: bits per pixel at ref_crf.
        "ref_crf": 23,
        "ref_bpp": 0.085,
        "extra_args": [],
        "blurb": "Plays everywhere — safest choice.",
    },
    "H.265 / HEVC": {
        "vcodec": "libx265",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "default_crf": 28,
        "crf_range": (22, 36),
        "ref_crf": 28,
        "ref_bpp": 0.050,
        # hvc1 tag keeps the file playable in Safari / QuickTime / Windows.
        "extra_args": ["-tag:v", "hvc1"],
        "blurb": "~30-50% smaller, slower to encode, less universal playback.",
    },
}

SPEED_PRESETS = ["ultrafast", "superfast", "veryfast", "faster",
                 "fast", "medium", "slow", "slower", "veryslow"]

# Friendly quality tiers. offset is applied to the codec's default CRF, so
# the same tier means the same rough quality on both codecs.
QUALITY_PRESETS = {
    "Best quality": {"offset": -4, "blurb": "Visually lossless, largest file."},
    "Balanced": {"offset": 0, "blurb": "Recommended — no visible loss for most video."},
    "Smaller file": {"offset": 4, "blurb": "Noticeably smaller, slight softening possible."},
    "Smallest": {"offset": 8, "blurb": "Aggressive — best for sharing over chat/email."},
}

AUDIO_MODES = {
    "Re-encode (128 kbps AAC)": "reencode",
    "Keep original audio": "copy",
    "Remove audio": "none",
}

WORK_DIR_PREFIX = "video_compress_"


def _binary(name: str) -> str:
    """Resolve an ffmpeg-family binary from env override or PATH."""
    override = os.environ.get(f"{name.upper()}_BINARY")
    if override and Path(override).exists():
        return override
    found = shutil.which(name)
    if found:
        return found
    raise FFmpegNotFoundError(
        f"`{name}` was not found. Install ffmpeg and make sure it is on your "
        f"PATH (or set {name.upper()}_BINARY to its full path)."
    )


@dataclass
class VideoInfo:
    duration_sec: float
    width: int
    height: int
    codec: str
    bitrate: Optional[int]
    size_bytes: int
    fps: float = 0.0
    has_audio: bool = False

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000


@dataclass
class CompressionResult:
    output_path: Path
    input_size_bytes: int
    output_size_bytes: int
    elapsed_sec: float = 0.0
    settings: Optional[dict] = None

    @property
    def reduction_pct(self) -> float:
        if self.input_size_bytes == 0:
            return 0.0
        return (1 - self.output_size_bytes / self.input_size_bytes) * 100

    @property
    def times_smaller(self) -> float:
        if self.output_size_bytes == 0:
            return 0.0
        return self.input_size_bytes / self.output_size_bytes


def check_ffmpeg() -> None:
    """Verify ffmpeg and ffprobe are available. Call once at app startup."""
    _binary("ffmpeg")
    _binary("ffprobe")


def _parse_fps(rate: Optional[str]) -> float:
    """Turn ffprobe's '30000/1001' style rate into a float."""
    if not rate:
        return 0.0
    try:
        if "/" in rate:
            num, den = rate.split("/")
            return float(num) / float(den) if float(den) else 0.0
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: Path) -> VideoInfo:
    """Read video metadata via ffprobe."""
    cmd = [
        _binary("ffprobe"), "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    fmt = data.get("format", {})

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    bitrate = fmt.get("bit_rate")

    return VideoInfo(
        duration_sec=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        codec=video_stream.get("codec_name", "unknown"),
        bitrate=int(bitrate) if bitrate else None,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        fps=_parse_fps(video_stream.get("avg_frame_rate")
                       or video_stream.get("r_frame_rate")),
        has_audio=has_audio,
    )


def resolve_crf(codec_label: str, quality_label: str) -> int:
    """Map a friendly quality tier onto a codec-specific CRF value."""
    preset = CODEC_PRESETS[codec_label]
    lo, hi = preset["crf_range"]
    crf = preset["default_crf"] + QUALITY_PRESETS[quality_label]["offset"]
    return max(lo, min(hi, crf))


def estimate_output_size(
    info: VideoInfo,
    codec_label: str,
    crf: int,
    target_height: Optional[int] = None,
    audio_mode: str = "reencode",
) -> Optional[int]:
    """
    Rough size estimate, in bytes, using a bits-per-pixel model that is
    then scaled by how "easy" the source appears to be.

    The base model assumes average camera footage. Screen recordings and
    animation compress far better than that, and their low source bitrate is
    the giveaway — so the model prediction is scaled down by the ratio
    between the real source bitrate and what the model would have predicted
    for the source itself. Still approximate: treat it as a ballpark hint,
    not a promise.
    """
    if not (info.duration_sec > 0 and info.width and info.height):
        return None

    fps = info.fps or 30.0
    src_w, src_h = info.width, info.height
    width, height = src_w, src_h
    if target_height and target_height < height:
        width = round(width * target_height / height)
        height = target_height

    preset = CODEC_PRESETS[codec_label]
    # Each 6 CRF steps roughly halves/doubles the bitrate.
    bpp = preset["ref_bpp"] * (2 ** ((preset["ref_crf"] - crf) / 6.0))
    video_bps = width * height * fps * bpp

    # Content-complexity correction from the source bitrate.
    if info.bitrate:
        ref = CODEC_PRESETS["H.264"]
        baseline_bps = src_w * src_h * fps * ref["ref_bpp"]
        src_video_bps = max(info.bitrate - (128_000 if info.has_audio else 0), 1)
        if baseline_bps > 0:
            video_bps *= max(0.10, min(1.0, src_video_bps / baseline_bps))

    if audio_mode == "none" or not info.has_audio:
        audio_bps = 0
    elif audio_mode == "copy":
        audio_bps = 192_000
    else:
        audio_bps = 128_000

    estimate = (video_bps + audio_bps) * info.duration_sec / 8
    # Re-encoding above the source size is possible in theory but the app
    # would never be useful there; clamp so the hint stays sane.
    return int(min(estimate, info.size_bytes))


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def compress_video(
    input_path: Path,
    output_path: Path,
    codec_label: str,
    crf: int,
    speed_preset: str = "medium",
    target_height: Optional[int] = None,
    audio_mode: str = "reencode",
    duration_sec: float = 0,
    on_progress: Optional[Callable[[float], None]] = None,
) -> CompressionResult:
    """
    Compress video using ffmpeg CRF encoding.

    Args:
        input_path: source video.
        output_path: destination (.mp4).
        codec_label: key from CODEC_PRESETS.
        crf: quality level (lower = better quality, larger file).
        speed_preset: encode speed/efficiency trade-off.
        target_height: downscale to this height (keeps aspect ratio).
        audio_mode: one of "reencode", "copy", "none".
        duration_sec: total duration, used for progress calculation.
        on_progress: callback receiving percentage [0-100].
    """
    preset = CODEC_PRESETS[codec_label]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _binary("ffmpeg"), "-y", "-hide_banner", "-nostdin",
        "-i", str(input_path),
        "-c:v", preset["vcodec"],
        "-crf", str(crf),
        "-preset", speed_preset,
        "-pix_fmt", preset["pix_fmt"],
        *preset["extra_args"],
        "-movflags", "+faststart",
    ]

    if audio_mode == "none":
        cmd.append("-an")
    elif audio_mode == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", preset["acodec"], "-b:a", "128k"]

    if target_height and target_height > 0:
        cmd += ["-vf", f"scale=-2:{target_height}:flags=lanczos"]

    cmd.append(str(output_path))

    started = time.time()
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    output_lines: list[str] = []
    with process:
        for line in process.stdout:  # type: ignore[union-attr]
            output_lines.append(line)
            if on_progress and duration_sec > 0:
                match = _TIME_RE.search(line)
                if match:
                    h, m, s = match.groups()
                    seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    on_progress(min(seconds / duration_sec * 100, 99.0))
        process.wait()

    if process.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {process.returncode}):\n"
            + "".join(output_lines[-20:])
        )

    if on_progress:
        on_progress(100.0)

    return CompressionResult(
        output_path=output_path,
        input_size_bytes=input_path.stat().st_size,
        output_size_bytes=output_path.stat().st_size,
        elapsed_sec=time.time() - started,
        settings={
            "codec": codec_label,
            "crf": crf,
            "preset": speed_preset,
            "height": target_height,
            "audio": audio_mode,
        },
    )


def cleanup_stale_workdirs(root: Path, max_age_sec: float = 2 * 3600,
                           keep: Optional[Path] = None) -> int:
    """
    Delete leftover per-session work directories older than max_age_sec.

    Sessions that end without a browser event (tab closed, server restart)
    would otherwise leave large files behind, which matters on a shared or
    hosted deployment with limited disk.
    """
    removed = 0
    now = time.time()
    for path in root.glob(f"{WORK_DIR_PREFIX}*"):
        if not path.is_dir() or (keep and path == keep):
            continue
        try:
            if now - path.stat().st_mtime > max_age_sec:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def fmt_size(num_bytes: float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def fmt_duration(seconds: float) -> str:
    """Human-readable duration, e.g. 95 -> '1m 35s'."""
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
