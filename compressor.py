"""Reliable FFmpeg-based video compression helpers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be located."""


class CompressionError(RuntimeError):
    """Raised when probing or compression fails."""


CODEC_PRESETS = {
    "H.264": {"vcodec": "libx264", "acodec": "aac", "pix_fmt": "yuv420p",
              "default_crf": 23, "crf_range": (18, 32), "ref_crf": 23,
              "ref_bpp": 0.085, "extra_args": [],
              "blurb": "Plays everywhere — safest choice."},
    "H.265 / HEVC": {"vcodec": "libx265", "acodec": "aac", "pix_fmt": "yuv420p",
                     "default_crf": 28, "crf_range": (22, 36), "ref_crf": 28,
                     "ref_bpp": 0.050, "extra_args": ["-tag:v", "hvc1"],
                     "blurb": "Often smaller, slower to encode, less universal playback."},
}
SPEED_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"]
QUALITY_PRESETS = {
    "Best quality": {"offset": -4, "blurb": "Higher quality, usually larger file."},
    "Balanced": {"offset": 0, "blurb": "Recommended general-purpose setting."},
    "Smaller file": {"offset": 4, "blurb": "Smaller file; quality loss may be visible."},
    "Smallest": {"offset": 8, "blurb": "Aggressive compression."},
}
AUDIO_MODES = {"Re-encode (128 kbps AAC)": "reencode",
               "Keep original audio": "copy", "Remove audio": "none"}
WORK_DIR_PREFIX = "video_compress_"


def _binary(name: str) -> str:
    override = os.environ.get(f"{name.upper()}_BINARY")
    if override and Path(override).is_file():
        return override
    found = shutil.which(name)
    if found:
        return found
    raise FFmpegNotFoundError(
        f"`{name}` was not found. Install FFmpeg and ensure it is on PATH, "
        f"or set {name.upper()}_BINARY to its executable path."
    )


@dataclass
class VideoInfo:
    duration_sec: float
    width: int
    height: int
    codec: str
    bitrate: int | None
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
    settings: dict | None = None

    @property
    def reduction_pct(self) -> float:
        if not self.input_size_bytes:
            return 0.0
        return (1 - self.output_size_bytes / self.input_size_bytes) * 100

    @property
    def times_smaller(self) -> float:
        return self.input_size_bytes / self.output_size_bytes if self.output_size_bytes else 0.0


def check_ffmpeg() -> None:
    _binary("ffmpeg")
    _binary("ffprobe")


def _parse_fps(rate: str | None) -> float:
    if not rate:
        return 0.0
    try:
        numerator, denominator = rate.split("/", 1) if "/" in rate else (rate, "1")
        den = float(denominator)
        return float(numerator) / den if den else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: Path, timeout_sec: int = 30) -> VideoInfo:
    path = Path(path)
    if not path.is_file():
        raise CompressionError(f"Input file does not exist: {path.name}")
    cmd = [_binary("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True,
                              timeout=timeout_sec)
        data = json.loads(proc.stdout)
    except subprocess.TimeoutExpired as exc:
        raise CompressionError("Video metadata probing timed out.") from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise CompressionError(f"Could not read this video: {detail[-1500:]}") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise CompressionError("The selected file does not contain a video stream.")
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0)
        bitrate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise CompressionError("Video metadata contains invalid numeric values.") from exc
    if width <= 0 or height <= 0:
        raise CompressionError("Video dimensions are missing or invalid.")
    return VideoInfo(duration, width, height, video.get("codec_name", "unknown"),
                     bitrate, int(fmt.get("size") or path.stat().st_size),
                     _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
                     any(s.get("codec_type") == "audio" for s in streams))


def resolve_crf(codec_label: str, quality_label: str) -> int:
    try:
        preset = CODEC_PRESETS[codec_label]
        offset = QUALITY_PRESETS[quality_label]["offset"]
    except KeyError as exc:
        raise ValueError(f"Unsupported codec or quality preset: {exc.args[0]}") from exc
    low, high = preset["crf_range"]
    return max(low, min(high, preset["default_crf"] + offset))


def estimate_output_size(info: VideoInfo, codec_label: str, crf: int,
                         target_height: int | None = None,
                         audio_mode: str = "reencode") -> int | None:
    """Return a deliberately approximate size estimate in bytes."""
    if not (info.duration_sec > 0 and info.width > 0 and info.height > 0):
        return None
    if codec_label not in CODEC_PRESETS:
        raise ValueError(f"Unsupported codec: {codec_label}")
    fps = info.fps or 30.0
    width, height = info.width, info.height
    if target_height and target_height < height:
        width, height = round(width * target_height / height), target_height
    preset = CODEC_PRESETS[codec_label]
    bpp = preset["ref_bpp"] * (2 ** ((preset["ref_crf"] - crf) / 6.0))
    video_bps = width * height * fps * bpp
    if info.bitrate:
        baseline = info.width * info.height * fps * CODEC_PRESETS["H.264"]["ref_bpp"]
        source_video_bps = max(info.bitrate - (128_000 if info.has_audio else 0), 1)
        if baseline > 0:
            video_bps *= max(0.10, min(1.0, source_video_bps / baseline))
    audio_bps = 0 if audio_mode == "none" or not info.has_audio else (
        192_000 if audio_mode == "copy" else 128_000)
    return int(min((video_bps + audio_bps) * info.duration_sec / 8, info.size_bytes))


def _validate_options(codec_label: str, crf: int, speed_preset: str,
                      target_height: int | None, audio_mode: str) -> None:
    if codec_label not in CODEC_PRESETS:
        raise ValueError(f"Unsupported codec: {codec_label}")
    low, high = CODEC_PRESETS[codec_label]["crf_range"]
    if not isinstance(crf, int) or not low <= crf <= high:
        raise ValueError(f"CRF must be an integer between {low} and {high}.")
    if speed_preset not in SPEED_PRESETS:
        raise ValueError("Unsupported encoding speed preset.")
    if target_height is not None and (
        not isinstance(target_height, int) or target_height <= 0 or target_height > 16384
    ):
        raise ValueError("Target height must be a positive integer.")
    if audio_mode not in {"reencode", "copy", "none"}:
        raise ValueError("Unsupported audio mode.")


def compress_video(input_path: Path, output_path: Path, codec_label: str, crf: int,
                   speed_preset: str = "medium", target_height: int | None = None,
                   audio_mode: str = "reencode", duration_sec: float = 0,
                   on_progress: Callable[[float], None] | None = None,
                   timeout_sec: int | None = None) -> CompressionResult:
    """Encode with FFmpeg progress protocol, bounded diagnostics and cleanup."""
    input_path, output_path = Path(input_path), Path(output_path)
    if not input_path.is_file():
        raise CompressionError("Input video does not exist.")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must be different.")
    _validate_options(codec_label, crf, speed_preset, target_height, audio_mode)
    if duration_sec < 0:
        raise ValueError("Duration cannot be negative.")

    preset = CODEC_PRESETS[codec_label]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
    temp_output.unlink(missing_ok=True)
    cmd = [_binary("ffmpeg"), "-y", "-hide_banner", "-nostdin",
           "-progress", "pipe:1", "-nostats", "-i", str(input_path),
           "-map", "0:v:0", "-c:v", preset["vcodec"], "-crf", str(crf),
           "-preset", speed_preset, "-pix_fmt", preset["pix_fmt"],
           *preset["extra_args"], "-movflags", "+faststart"]
    if audio_mode == "none":
        cmd += ["-an"]
    elif audio_mode == "copy":
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    else:
        cmd += ["-map", "0:a?", "-c:a", preset["acodec"], "-b:a", "128k"]
    if target_height is not None:
        cmd += ["-vf", f"scale=-2:min({target_height}\\,ih):flags=lanczos"]
    cmd.append(str(temp_output))

    started = time.monotonic()
    stderr_tail: list[str] = []
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, bufsize=1) as proc:
            def drain_stderr() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    stderr_tail.append(line.rstrip())
                    if len(stderr_tail) > 80:
                        del stderr_tail[:20]
            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            last_pct = 0.0
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    if line.startswith("out_time=") and duration_sec > 0:
                        stamp = line.partition("=")[2].strip()
                        try:
                            hours, minutes, seconds = stamp.split(":")
                            elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                            last_pct = min(99.0, max(last_pct, elapsed / duration_sec * 100))
                            if on_progress:
                                on_progress(last_pct)
                        except ValueError:
                            pass
                    elif line.strip() == "progress=end" and on_progress:
                        on_progress(100.0)
                try:
                    return_code = proc.wait(timeout=timeout_sec)
                except subprocess.TimeoutExpired as exc:
                    proc.kill()
                    proc.wait()
                    raise CompressionError(
                        f"Encoding exceeded the {timeout_sec}s timeout."
                    ) from exc
            except BaseException:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                raise
            stderr_thread.join(timeout=2)
            if return_code != 0:
                raise CompressionError("FFmpeg failed:\n" + "\n".join(stderr_tail[-30:]))
        if not temp_output.is_file() or temp_output.stat().st_size == 0:
            raise CompressionError("FFmpeg completed without producing a valid output file.")
        temp_output.replace(output_path)
        return CompressionResult(output_path, input_path.stat().st_size,
                                 output_path.stat().st_size, time.monotonic() - started,
                                 {"codec": codec_label, "crf": crf,
                                  "preset": speed_preset, "height": target_height,
                                  "audio": audio_mode})
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError("FFmpeg executable could not be started.") from exc
    finally:
        temp_output.unlink(missing_ok=True)


def cleanup_stale_workdirs(root: Path, max_age_sec: float = 2 * 3600,
                           keep: Path | None = None) -> int:
    """Remove only stale app-owned workdirs."""
    removed, now = 0, time.time()
    for path in Path(root).glob(f"{WORK_DIR_PREFIX}*"):
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
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
