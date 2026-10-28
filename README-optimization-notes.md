# Optimization patch notes

This branch hardens FFmpeg process management while preserving the public names used by app.py, including estimate_output_size.

Run locally:
```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check compressor.py tests
pytest --cov=compressor --cov-report=term-missing
```

The CI tests are unit tests. Real FFmpeg integration tests, a Docker smoke test, and end-to-end Streamlit validation remain follow-up work. No performance gains are claimed without benchmarks.
