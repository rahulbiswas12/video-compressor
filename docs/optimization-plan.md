# Video Compressor optimization plan

## Changes in this branch
- Harden FFprobe calls with a timeout and clearer malformed-input errors.
- Validate codec, CRF, speed, scaling height and audio settings at the service boundary.
- Replace human-readable stderr progress parsing with FFmpeg's `-progress pipe:1` protocol.
- Drain stderr concurrently and retain only a bounded diagnostic tail.
- Apply a configurable encoding timeout and terminate/kill the process on exceptions.
- Encode to a temporary partial file and promote only after successful output validation.
- Add unit tests and a GitHub Actions lint/test workflow.

## Follow-up work
1. Add FFmpeg integration tests using short synthetic clips and verify audio modes and scaling.
2. Add upload byte limits and use a generated filename instead of embedding the user-supplied name in the path.
3. Refactor the Streamlit UI into smaller modules after the engine changes are validated.
4. Add Docker build smoke tests and test against the deployed Streamlit runtime.
5. Benchmark H.264/H.265 quality, output size and runtime before changing defaults.

## Safety
This change is proposed on a feature branch and does not modify `main`. Review the diff and wait for CI before merging.
