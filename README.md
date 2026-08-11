# 🎬 Video Compressor

A Streamlit app that shrinks recorded videos to a fraction of their size
while preserving visual quality, using ffmpeg's CRF (Constant Rate Factor)
encoding.

- Quality tiers (Best / Balanced / Smaller / Smallest) that map to
  codec-aware CRF values, with a CRF slider for fine tuning
- H.264 or H.265/HEVC, optional downscaling, audio re-encode / copy / strip
- Rough output-size estimate **before** you spend time encoding
- Live progress with an ETA, before/after size bars, inline preview and a
  streaming download
- Optional password gate and duration limits for public deployments

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/download.html) on your `PATH` (both `ffmpeg`
  and `ffprobe`). Alternatively set `FFMPEG_BINARY` / `FFPROBE_BINARY` to
  full paths.

## Run locally

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

## Usage

1. Drop in a video (mp4, mov, mkv, avi, webm, m4v, mpg, wmv, flv).
2. Pick a **quality tier** — *Balanced* is visually indistinguishable from
   the source for most recordings.
3. Choose a **codec**. H.264 plays everywhere; H.265 files are ~30–50%
   smaller but encode slower and are less universally supported.
4. Optionally **downscale** the resolution — the biggest size lever after
   quality.
5. Under **Advanced**: fine-tune CRF, trade encode time for efficiency with
   the speed preset, or drop/copy the audio track.
6. Check the estimate, hit **Compress**, then preview and download.

## Deploy for other users

### Option A — Streamlit Community Cloud (free, easiest)

1. Push this folder to a **GitHub** repository. (Git isn't installed on this
   machine — install it from https://git-scm.com/download/win, or use
   GitHub's "Add file → Upload files" page in the browser.)

   ```powershell
   git init
   git add .
   git commit -m "Video compressor app"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```

2. Go to https://share.streamlit.io → **Create app** → pick the repo,
   branch `main`, main file `app.py` → **Deploy**.

3. `packages.txt` (containing `ffmpeg`) is what makes this work there —
   Streamlit installs it with apt during the build, which provides both
   `ffmpeg` and `ffprobe`. `requirements.txt` covers the Python side.

4. **Upload limit.** `.streamlit/config.toml` ships with
   `maxUploadSize = 500` (MB), which is deliberately conservative: Streamlit
   buffers an upload in RAM before the app writes it to disk, and free-tier
   containers have limited memory and scratch disk. Multi-GB uploads need
   Option B.

5. Anyone with the URL can use the app, and the container is shared: two
   simultaneous encodes compete for the same CPU. To restrict access, add a
   secret in **App settings → Secrets**:

   ```toml
   APP_PASSWORD = "your-shared-password"
   ```

   See `.streamlit/secrets.toml.example`. Without it the app is fully open —
   fine for a small team, not for anything sensitive. Uploaded videos are
   written to the container's temp folder and deleted when the session is
   reset or after two hours, but while present they are readable by anything
   else running in that container.

### Option B — Docker (best for large files)

```powershell
docker build -t video-compressor .
docker run -p 8501:8501 video-compressor
```

The image bundles ffmpeg and runs as a non-root user. Deploy it to any
container host (Azure Container Apps, Cloud Run, Fly.io, Hugging Face
Spaces, or your own VM) and size the CPU/RAM to your videos. Encoding is
CPU-bound: more cores means faster encodes.

Note that this exposes an **unauthenticated** web service. Put it behind
your identity-aware proxy / VPN, or set `APP_PASSWORD`, before opening it to
the internet.

### Optional configuration (environment variables)

| Variable | Effect |
| --- | --- |
| `APP_PASSWORD` | Require a shared password before the app loads |
| `MAX_DURATION_MIN` | Reject videos longer than N minutes |
| `MAX_ENCODE_PRESET` | Cap the slowest selectable preset, e.g. `medium` |
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | Override the upload limit (MB) |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | Explicit paths to the binaries |

## Upload size limit

Set in `.streamlit/config.toml`, currently **500 MB**:

```toml
[server]
maxUploadSize = 500
maxMessageSize = 500
```

Streamlit's built-in default is 200 MB. Raise this for local use — 2048 (2
GB) is fine on a desktop — but remember Streamlit holds the upload in memory
before the app streams it to disk, so peak RAM is roughly the file size.
Compressed output is streamed from disk to the browser, and the inline
preview is skipped for outputs above 150 MB.

## How it works

Instead of compressing to a fixed bitrate (which can hurt quality on complex
scenes and waste space on simple ones), the app uses ffmpeg's CRF mode. CRF
targets a constant *visual quality* level and lets the encoder allocate bits
adaptively per frame — the standard way to cut file size without a
perceptible quality loss.

The pre-encode estimate uses a bits-per-pixel model scaled by how efficient
the source already looks, so screen recordings aren't overestimated. It is a
ballpark, not a guarantee.

## Tests

```powershell
python tests\test_smoke.py
```

Covers ffprobe parsing, quality→CRF mapping, the size estimate, real H.264
and H.265 encodes, downscaling, audio stripping, ffmpeg failure handling,
temp-dir cleanup, and the Streamlit UI end to end (upload → compress →
result) via `streamlit.testing`. Requires ffmpeg.

## Files

- `app.py` — Streamlit UI.
- `compressor.py` — ffmpeg wrapper: probing, size estimate, CRF compression
  with progress reporting, temp cleanup.
- `.streamlit/config.toml` — upload limit and theme.
- `packages.txt` — apt packages for Streamlit Community Cloud (ffmpeg).
- `Dockerfile` / `.dockerignore` — self-hosting image.
- `requirements.txt` — Python dependencies.
- `tests/` — smoke tests.
