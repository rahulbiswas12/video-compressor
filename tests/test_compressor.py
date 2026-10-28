import pytest

from compressor import (
    CODEC_PRESETS, QUALITY_PRESETS, SPEED_PRESETS, VideoInfo,
    _parse_fps, _validate_options, estimate_output_size, fmt_duration,
    fmt_size, resolve_crf,
)


@pytest.mark.parametrize(("rate", "expected"), [
    ("30000/1001", 29.97002997), ("24", 24.0), (None, 0.0),
    ("0/0", 0.0), ("bad", 0.0),
])
def test_parse_fps(rate, expected):
    assert _parse_fps(rate) == pytest.approx(expected)


@pytest.mark.parametrize("codec", CODEC_PRESETS)
@pytest.mark.parametrize("quality", QUALITY_PRESETS)
def test_crf_stays_in_range(codec, quality):
    crf = resolve_crf(codec, quality)
    low, high = CODEC_PRESETS[codec]["crf_range"]
    assert low <= crf <= high


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        resolve_crf("invalid", "Balanced")


def test_options_validation():
    with pytest.raises(ValueError):
        _validate_options("H.264", 99, "medium", None, "reencode")
    with pytest.raises(ValueError):
        _validate_options("H.264", 23, "invalid", None, "reencode")
    with pytest.raises(ValueError):
        _validate_options("H.264", 23, "medium", 0, "reencode")


def test_format_helpers():
    assert fmt_duration(3661) == "1h 1m"
    assert fmt_duration(-1) == "0s"
    assert fmt_size(0) == "0.0 B"


def test_size_estimate_is_none_without_duration():
    info = VideoInfo(0, 1920, 1080, "h264", 1_000_000, 500_000)
    assert estimate_output_size(info, "H.264", 23) is None


def test_size_estimate_is_bounded_by_source_size():
    info = VideoInfo(60, 1920, 1080, "h264", 3_000_000, 10_000_000, 30, True)
    estimate = estimate_output_size(info, "H.264", 23)
    assert estimate is not None
    assert 0 <= estimate <= info.size_bytes
