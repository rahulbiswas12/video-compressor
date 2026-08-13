"""
Streamlit UI for compressing videos with ffmpeg CRF encoding.

Run with:  streamlit run app.py

Deployment notes:
  * Upload ceiling comes from .streamlit/config.toml (server.maxUploadSize),
    overridable with STREAMLIT_SERVER_MAX_UPLOAD_SIZE.
  * Optional guard rails for public hosting (all optional env vars):
      APP_PASSWORD           - gate the app behind a shared password
      MAX_DURATION_MIN       - reject videos longer than N minutes
      MAX_ENCODE_PRESET      - cap the slowest allowed x264/x265 preset
    APP_PASSWORD may also be supplied via Streamlit secrets.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

from compressor import (
    AUDIO_MODES,
    CODEC_PRESETS,
    QUALITY_PRESETS,
    SPEED_PRESETS,
    WORK_DIR_PREFIX,
    FFmpegNotFoundError,
    check_ffmpeg,
    cleanup_stale_workdirs,
    compress_video,
    fmt_duration,
    fmt_size,
    probe_video,
    resolve_crf,
)

# Inline preview is skipped above this size — embedding a huge file in the
# page is slow and pointless when a download button is right there.
PREVIEW_LIMIT_BYTES = 150 * 1024 * 1024
ACCEPTED_TYPES = ["mp4", "mov", "mkv", "avi", "webm", "m4v", "mpg", "mpeg", "wmv", "flv"]

st.set_page_config(
    page_title="Video Compressor",
    page_icon="🎬",
    layout="centered",
    menu_items={"about": "Shrink videos with ffmpeg CRF encoding."},
)

CSS = """
<style>
/* ---------- layout ---------- */
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 900px; }

/* ---------- hero ---------- */
.hero { margin-bottom: 1.6rem; }
.hero h1 {
  font-size: 2.5rem; font-weight: 800; line-height: 1.15; margin: 0 0 .35rem 0;
  background: linear-gradient(92deg, #FF6B6B 0%, #FF4B4B 45%, #C026D3 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.hero p { margin: 0; opacity: .72; font-size: 1.02rem; }

/* ---------- section labels ---------- */
.section-label {
  text-transform: uppercase; letter-spacing: .09em; font-size: .72rem;
  font-weight: 700; opacity: .55; margin: 1.5rem 0 .5rem 0;
}

/* ---------- stat strip ---------- */
.stat-row { display: flex; flex-wrap: wrap; gap: .5rem; }
.stat {
  flex: 1 1 120px; padding: .7rem .85rem; border-radius: 12px;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.09);
}
.stat .k { font-size: .68rem; text-transform: uppercase; letter-spacing: .07em; opacity: .55; }
.stat .v { font-size: 1.06rem; font-weight: 700; margin-top: .15rem; }

/* ---------- result banner ---------- */
.result-banner {
  padding: 1.1rem 1.25rem; border-radius: 14px; margin-bottom: .9rem;
  background: linear-gradient(92deg, rgba(16,185,129,.16), rgba(16,185,129,.03));
  border: 1px solid rgba(16,185,129,.42);
}
.result-banner .headline { font-size: 1.25rem; font-weight: 800; }
.result-banner .detail { opacity: .78; font-size: .9rem; margin-top: .2rem; }

/* ---------- size comparison bars ---------- */
.bars { margin: .3rem 0 .9rem 0; }
.bar-row { display: flex; align-items: center; gap: .7rem; margin-bottom: .45rem; }
.bar-row .label { width: 4.2rem; font-size: .78rem; opacity: .65; text-align: right; }
.bar-track { flex: 1; height: 16px; border-radius: 8px; background: rgba(255,255,255,.06); overflow: hidden; }
.bar-fill { height: 100%; border-radius: 8px; }
.bar-fill.before { background: linear-gradient(90deg, #64748B, #94A3B8); }
.bar-fill.after  { background: linear-gradient(90deg, #FF4B4B, #F59E0B); }
.bar-row .val { width: 5.2rem; font-size: .82rem; font-weight: 700; }

/* ---------- controls polish ---------- */
[data-testid="stFileUploaderDropzone"] {
  border: 1.5px dashed rgba(255,255,255,.22); border-radius: 14px;
  background: rgba(255,255,255,.03);
}
div.stButton > button { border-radius: 10px; font-weight: 700; min-height: 48px; }
div.stDownloadButton > button { border-radius: 10px; font-weight: 700; min-height: 48px; }
footer, #MainMenu { visibility: hidden; }
.app-footer { margin-top: 2.5rem; text-align: center; font-size: .78rem; opacity: .45; }

/* ---------- mobile responsive ---------- */
@media (max-width: 768px) {
  .block-container { padding-top: 1.2rem; padding-bottom: 2rem; padding-left: 1rem; padding-right: 1rem; }

  /* Hero scales down */
  .hero h1 { font-size: 1.75rem; }
  .hero p { font-size: .92rem; }

  /* Stats wrap into a 2-column grid on mobile */
  .stat-row { gap: .4rem; }
  .stat { flex: 1 1 calc(50% - .4rem); padding: .55rem .7rem; }
  .stat .v { font-size: .92rem; }

  /* Result banner */
  .result-banner { padding: .9rem 1rem; }
  .result-banner .headline { font-size: 1.05rem; }
  .result-banner .detail { font-size: .82rem; }

  /* Size bars — shrink labels */
  .bar-row { gap: .4rem; }
  .bar-row .label { width: 3rem; font-size: .7rem; }
  .bar-row .val { width: 4.2rem; font-size: .75rem; }

  /* Segmented control text wrapping */
  [data-testid="stSegmentedControl"] button {
    font-size: .72rem !important;
    padding: .5rem .4rem !important;
    min-height: 44px;
  }

  /* Streamlit columns stack on mobile — force full width */
  [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 100% !important;
    min-width: 100% !important;
  }

  /* Touch-friendly inputs */
  [data-testid="stFileUploaderDropzone"] { min-height: 120px; border-radius: 12px; }
  div.stButton > button, div.stDownloadButton > button {
    min-height: 52px; font-size: .95rem;
  }

  /* Radio and select spacing */
  [data-testid="stRadio"] label,
  [data-testid="stSelectbox"] label {
    font-size: .88rem;
  }
}

/* Extra small screens (< 400px, e.g. older phones) */
@media (max-width: 400px) {
  .hero h1 { font-size: 1.5rem; }
  .stat { flex: 1 1 100%; }
  .bar-row .label { width: 2.5rem; font-size: .65rem; }
  .bar-row .val { width: 3.8rem; font-size: .7rem; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Optional password gate (only active when APP_PASSWORD is configured)
# --------------------------------------------------------------------------- #
def _configured_password() -> str | None:
    try:
        secret = st.secrets.get("APP_PASSWORD")  # type: ignore[union-attr]
    except Exception:
        secret = None
    return secret or os.environ.get("APP_PASSWORD") or None


def require_password() -> None:
    password = _configured_password()
    if not password or st.session_state.get("authed"):
        return
    st.markdown(
        '<div class="hero"><h1>🎬 Video Compressor</h1>'
        "<p>Enter the access password to continue.</p></div>",
        unsafe_allow_html=True,
    )
    entered = st.text_input("Password", type="password")
    if entered:
        if entered == password:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_password()


# --------------------------------------------------------------------------- #
# Environment checks and per-session scratch space
# --------------------------------------------------------------------------- #
try:
    check_ffmpeg()
except FFmpegNotFoundError as e:
    st.error(str(e))
    st.caption(
        "On Streamlit Community Cloud this is handled by a `packages.txt` "
        "file containing `ffmpeg`."
    )
    st.stop()

TMP_ROOT = Path(tempfile.gettempdir())
if "work_dir" not in st.session_state:
    cleanup_stale_workdirs(TMP_ROOT)
    st.session_state.work_dir = tempfile.mkdtemp(prefix=WORK_DIR_PREFIX, dir=TMP_ROOT)
    st.session_state.result = None
    st.session_state.saved_name = None
WORK_DIR = Path(st.session_state.work_dir)


def reset_session() -> None:
    """Drop the current file and results, freeing disk on shared hosts."""
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    st.session_state.result = None
    st.session_state.saved_name = None
    st.session_state.uploader_key = st.session_state.get("uploader_key", 0) + 1


def stat_strip(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="stat"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in items
    )
    st.markdown(f'<div class="stat-row">{cells}</div>', unsafe_allow_html=True)


def size_bars(before: int, after: int) -> None:
    after_pct = max(2.0, after / before * 100) if before else 0
    st.markdown(
        f'<div class="bars">'
        f'<div class="bar-row"><div class="label">Before</div>'
        f'<div class="bar-track"><div class="bar-fill before" style="width:100%"></div></div>'
        f'<div class="val">{fmt_size(before)}</div></div>'
        f'<div class="bar-row"><div class="label">After</div>'
        f'<div class="bar-track"><div class="bar-fill after" style="width:{after_pct:.1f}%"></div></div>'
        f'<div class="val">{fmt_size(after)}</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Header + upload
# --------------------------------------------------------------------------- #
max_upload_mb = int(st.get_option("server.maxUploadSize"))
max_duration_min = float(os.environ.get("MAX_DURATION_MIN") or 0)

st.markdown(
    '<div class="hero"><h1>🎬 Video Compressor</h1>'
    "<p>Shrink recordings to a fraction of their size with ffmpeg CRF "
    "encoding — quality stays, bytes go.</p></div>",
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    f"Drop a video here  ·  up to {max_upload_mb} MB",
    type=ACCEPTED_TYPES,
    key=f"uploader_{st.session_state.get('uploader_key', 0)}",
)

if uploaded is None:
    st.session_state.result = None
    # On mobile these will stack vertically thanks to the CSS media query
    # that forces stColumn to 100% width on narrow screens.
    c1, c2, c3 = st.columns(3, gap="small")
    for col, (icon, title, body) in zip(
        (c1, c2, c3),
        [
            ("🎯", "Quality-first", "CRF encoding targets a visual quality level "
             "instead of a fixed bitrate, so bits go where they matter."),
            ("📉", "5-10× smaller", "Typical screen recordings and phone footage "
             "shrink dramatically with no visible difference."),
            ("🔒", "Nothing kept", "Files live in a temporary folder for your "
             "session only and are cleaned up automatically."),
        ],
    ):
        with col.container(border=True):
            st.markdown(f"**{icon} {title}**")
            st.caption(body)
    st.markdown(
        '<div class="app-footer">Powered by ffmpeg · CRF (Constant Rate Factor) encoding</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# Stream to disk in chunks rather than materialising the whole file as a
# bytes object — matters a lot for multi-hundred-MB uploads.
input_path = WORK_DIR / f"input_{uploaded.name}"
if (st.session_state.saved_name != uploaded.name
        or not input_path.exists()
        or input_path.stat().st_size != uploaded.size):
    with st.spinner("Reading upload…"):
        uploaded.seek(0)
        with open(input_path, "wb") as f:
            shutil.copyfileobj(uploaded, f, length=8 * 1024 * 1024)
    st.session_state.saved_name = uploaded.name
    st.session_state.result = None

try:
    info = probe_video(input_path)
except Exception as e:
    st.error(f"Could not read this video: {e}")
    st.button("Try another file", on_click=reset_session)
    st.stop()

if max_duration_min and info.duration_sec > max_duration_min * 60:
    st.error(
        f"This video is {fmt_duration(info.duration_sec)} long; this instance "
        f"accepts up to {max_duration_min:g} minutes."
    )
    st.button("Try another file", on_click=reset_session)
    st.stop()

st.markdown('<div class="section-label">Source</div>', unsafe_allow_html=True)
stat_strip([
    ("Size", fmt_size(info.size_bytes)),
    ("Resolution", f"{info.width}×{info.height}" if info.width else "—"),
    ("Duration", fmt_duration(info.duration_sec)),
    ("Frame rate", f"{info.fps:.0f} fps" if info.fps else "—"),
    ("Codec", info.codec),
])
with st.expander("Preview source"):
    st.video(str(input_path))
    if input_path.suffix.lower() not in (".mp4", ".webm", ".mov"):
        st.caption("Some container formats cannot play inline in the browser.")

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
st.markdown('<div class="section-label">Settings</div>', unsafe_allow_html=True)

with st.container(border=True):
    quality_label = st.segmented_control(
        "Quality",
        list(QUALITY_PRESETS.keys()),
        default="Balanced",
        help="Presets map to an ffmpeg CRF value tuned per codec.",
    ) or "Balanced"
    st.caption(QUALITY_PRESETS[quality_label]["blurb"])

    col_a, col_b = st.columns(2, gap="small")
    codec_label = col_a.radio(
        "Codec",
        list(CODEC_PRESETS.keys()),
        captions=[CODEC_PRESETS[k]["blurb"] for k in CODEC_PRESETS],
    )
    res_options = ["Original", 1080, 720, 480, 360]
    res_choice = col_b.selectbox(
        "Resolution",
        res_options,
        format_func=lambda v: v if v == "Original" else f"{v}p",
        help="Downscaling is the single biggest size lever after quality.",
    )

    target_height = None if res_choice == "Original" else int(res_choice)
    if target_height and info.height and target_height >= info.height:
        col_b.caption("Already at or below this height — no downscaling applied.")
        target_height = None

    crf = resolve_crf(codec_label, quality_label)

    with st.expander("Advanced"):
        adv_a, adv_b = st.columns(2, gap="small")
        with adv_a:
            crf = st.slider(
                "CRF (fine tune)",
                *CODEC_PRESETS[codec_label]["crf_range"],
                value=crf,
                help="Lower = better quality and a bigger file. Overrides the "
                     "quality preset above.",
            )
            allowed_speeds = SPEED_PRESETS
            cap = os.environ.get("MAX_ENCODE_PRESET")
            if cap in SPEED_PRESETS:
                allowed_speeds = SPEED_PRESETS[: SPEED_PRESETS.index(cap) + 1]
            speed_preset = st.select_slider(
                "Encoding speed",
                allowed_speeds,
                value="medium" if "medium" in allowed_speeds else allowed_speeds[-1],
                help="Slower = smaller file at the same quality, longer encode.",
            )
        with adv_b:
            audio_label = st.radio(
                "Audio",
                list(AUDIO_MODES.keys()),
                disabled=not info.has_audio,
                help="Re-encoding audio to 128 kbps AAC usually saves a little "
                     "more; copying is instant and lossless.",
            )
            if not info.has_audio:
                st.caption("This file has no audio track.")

audio_mode = AUDIO_MODES[audio_label] if info.has_audio else "none"

go = st.button("🚀 Compress video", type="primary", use_container_width=True)

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
if go:
    output_name = f"{Path(uploaded.name).stem}_compressed.mp4"
    output_path = WORK_DIR / output_name
    progress_slot = st.empty()
    bar = progress_slot.progress(0, text="Starting ffmpeg…")
    start = time.time()

    def report(pct: float) -> None:
        elapsed = time.time() - start
        eta = (elapsed / pct * (100 - pct)) if pct > 1 else 0
        suffix = f" · about {fmt_duration(eta)} left" if eta > 1 else ""
        bar.progress(int(pct), text=f"Compressing… {pct:.0f}%{suffix}")

    try:
        st.session_state.result = compress_video(
            input_path=input_path,
            output_path=output_path,
            codec_label=codec_label,
            crf=crf,
            speed_preset=speed_preset,
            target_height=target_height,
            audio_mode=audio_mode,
            duration_sec=info.duration_sec,
            on_progress=report,
        )
        progress_slot.empty()
    except RuntimeError as e:
        progress_slot.empty()
        st.session_state.result = None
        st.error("Compression failed.")
        with st.expander("ffmpeg output"):
            st.code(str(e))

# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
result = st.session_state.get("result")
if result is not None and result.output_path.exists():
    st.markdown('<div class="section-label">Result</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="result-banner">'
        f'<div class="headline">Saved {result.reduction_pct:.0f}% — '
        f"{fmt_size(result.input_size_bytes)} → {fmt_size(result.output_size_bytes)}</div>"
        f'<div class="detail">{result.times_smaller:.1f}× smaller · encoded in '
        f"{fmt_duration(result.elapsed_sec)}</div></div>",
        unsafe_allow_html=True,
    )
    size_bars(result.input_size_bytes, result.output_size_bytes)

    with open(result.output_path, "rb") as f:
        # Pass an open handle so Streamlit streams the file instead of us
        # holding the entire video in memory as a bytes object.
        st.download_button(
            f"⬇️  Download {result.output_path.name}",
            data=f,
            file_name=result.output_path.name,
            mime="video/mp4",
            type="primary",
            use_container_width=True,
        )

    if result.output_size_bytes <= PREVIEW_LIMIT_BYTES:
        with st.expander("Preview result", expanded=True):
            st.video(str(result.output_path))
            if CODEC_PRESETS[codec_label]["vcodec"] == "libx265":
                st.caption(
                    "HEVC may not play inline in every browser — the download "
                    "is still valid."
                )
    else:
        st.info("Inline preview skipped for a file this large — download to view.")

    st.button("Compress another video", on_click=reset_session,
              use_container_width=True)

st.markdown(
    '<div class="app-footer">Powered by ffmpeg · CRF (Constant Rate Factor) encoding</div>',
    unsafe_allow_html=True,
)
