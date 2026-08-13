<div align="center">

# 🎬 Video Compressor

### Shrink videos. Keep quality. No installs needed.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://videocompresser.streamlit.app/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<br>

**Drop a video → pick quality → get a file 5-10× smaller in seconds.**

No watermarks. No sign-ups. No upload to sketchy servers.

[🚀 **Try it live**](https://videocompresser.streamlit.app/) · [📖 Architecture](ARCHITECTURE.md) · [🐛 Report Bug](https://github.com/rahulbiswas12/video-compressor/issues)

<br>

</div>

---

## ✨ What it does

| Before | After |
|--------|-------|
| 500 MB screen recording | ~50 MB, same visual quality |
| 1.2 GB phone video | ~150 MB, indistinguishable |
| 80 MB meeting clip | ~12 MB, ready to share on Slack |

The app uses **ffmpeg's CRF (Constant Rate Factor)** encoding — the gold
standard for quality-preserving compression. Instead of a fixed bitrate, it
allocates bits adaptively per frame. Complex scenes get more, static frames
get less. The result: dramatically smaller files with no visible loss.

---

## 🎯 Features

- **🎚️ Quality tiers** — Best / Balanced / Smaller / Smallest, or fine-tune CRF manually
- **🔄 Dual codec** — H.264 (plays everywhere) or H.265/HEVC (30-50% smaller)
- **📐 Downscaling** — Drop to 1080p/720p/480p/360p with one click
- **🔊 Audio control** — Re-encode, keep original, or strip entirely
- **📊 Live progress** — Real-time percentage with ETA
- **📱 Mobile-friendly** — Fully responsive, works great on phones
- **🔒 Privacy-first** — Files stay in a temp folder, auto-cleaned after 2 hours
- **🔐 Optional password gate** — Lock it down for your team

---

## 🖥️ Screenshots

> Upload a video, tweak settings, hit compress, download the result.

```
┌────────────────────────────────────┐
│  🎬 Video Compressor               │
│                                    │
│  [  Drop a video here  ·  500 MB ] │
│                                    │
│  ── SOURCE ──────────────────────  │
│  Size: 487 MB  │  1920×1080        │
│  Duration: 12m │  30 fps │ h264    │
│                                    │
│  ── SETTINGS ────────────────────  │
│  Quality: [Best|Balanced|Smaller]  │
│  Codec: ○ H.264  ○ H.265          │
│  Resolution: [720p ▾]             │
│                                    │
│  [ 🚀 Compress video            ]  │
│                                    │
│  ── RESULT ──────────────────────  │
│  Saved 87% — 487 MB → 63 MB       │
│  7.7× smaller · encoded in 2m 14s │
│  Before ████████████████████ 487MB │
│  After  ██▌                  63MB  │
│                                    │
│  [ ⬇️  Download compressed.mp4  ]  │
└────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Use online (no setup)

👉 **https://videocompresser.streamlit.app/**

### Run locally

```bash
# Clone
git clone https://github.com/rahulbiswas12/video-compressor.git
cd video-compressor

# Setup
python -m venv venv
source venv/bin/activate        # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run
streamlit run app.py
```

> **Requires:** Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH.

### Docker

```bash
docker build -t video-compressor .
docker run -p 8501:8501 video-compressor
```

---

## 🛠️ How CRF Works

```
Traditional encoding:          CRF encoding (what this app uses):
┌─────────────────────┐       ┌─────────────────────┐
│ Fixed bitrate       │       │ Fixed quality        │
│ ════════════════    │       │ ─────/\──────/\───   │
│ Same bits whether   │       │ More bits on complex │
│ the scene needs     │       │ frames, fewer on     │
│ them or not.        │       │ simple ones.         │
│                     │       │                      │
│ Result: waste OR    │       │ Result: smallest     │
│ quality drops       │       │ file at your chosen  │
│                     │       │ quality level.       │
└─────────────────────┘       └─────────────────────┘
```

**CRF scale:** Lower = better quality + bigger file. The "Balanced" preset
(CRF 23 for H.264, 28 for H.265) is visually lossless for most content.

---

## ⚙️ Configuration

| Environment Variable | Effect |
|---------------------|--------|
| `APP_PASSWORD` | Gate the app behind a shared password |
| `MAX_DURATION_MIN` | Reject videos longer than N minutes |
| `MAX_ENCODE_PRESET` | Cap the slowest encoder preset |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | Custom paths to ffmpeg binaries |

---

## 📁 Project Structure

```
├── app.py                 → Streamlit UI (entry point)
├── compressor.py          → ffmpeg wrapper & encoding logic
├── requirements.txt       → Python dependencies
├── packages.txt           → System packages (ffmpeg for Streamlit Cloud)
├── Dockerfile             → Container deployment
├── .streamlit/
│   └── config.toml        → Upload limits & dark theme
└── tests/
    └── test_smoke.py      → Unit + integration + E2E tests
```

---

## 🧪 Tests

```bash
python tests/test_smoke.py
```

Covers probing, CRF mapping, encoding (H.264 + H.265), downscaling, audio
stripping, error handling, temp cleanup, and full Streamlit UI flow.

---

## 🤝 Contributing

1. Fork it
2. Create your branch (`git checkout -b feature/awesome`)
3. Commit changes (`git commit -m 'Add awesome feature'`)
4. Push (`git push origin feature/awesome`)
5. Open a Pull Request

---

## 📝 License

MIT — do whatever you want with it.

---

<div align="center">

**Built with [Streamlit](https://streamlit.io) + [ffmpeg](https://ffmpeg.org)**

⭐ Star this repo if it saved you some disk space!

</div>
