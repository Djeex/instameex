"""End-to-end: runs the real ultrahdr_app + exiftool (present in the Docker
image, skipped elsewhere) to catch regressions from dependency or base image
updates that the mocked unit tests cannot see."""
import shutil

import numpy as np
import pytest
import tifffile
from PIL import Image

from app import assembler

pytestmark = pytest.mark.skipif(
    bool(assembler.check_dependencies()) or not shutil.which("exiftool"),
    reason="ultrahdr_app/exiftool not installed",
)

SIZE = 128


def gradient():
    """A horizontal ramp 0..1 with a bright highlight block, as float values."""
    ramp = np.tile(np.linspace(0.05, 1.0, SIZE, dtype=np.float32), (SIZE, 1))
    img = np.stack([ramp, ramp, ramp], axis=-1)
    return img


@pytest.fixture
def sdr(tmp_path):
    arr = (np.clip(gradient() ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)
    path = tmp_path / "sdr.jpg"
    Image.fromarray(arr).save(path, "JPEG", quality=95)
    return path


@pytest.fixture
def hdr_tiff(tmp_path):
    hdr = gradient()
    hdr[:32, :32] *= 3.0  # highlight brighter than SDR white
    path = tmp_path / "hdr.tif"
    tifffile.imwrite(path, hdr.astype(np.float32), photometric="rgb")
    return path


def assert_valid_ultrahdr(out, log):
    assert out.exists() and out.stat().st_size > 0
    with Image.open(out) as img:
        assert img.format == "JPEG" and img.size == (SIZE, SIZE)
    assert "Validation report" in log  # gain map found and readable
    assert "XMP-hdrgm:GainMapMax" in log


def test_tiff_pipeline_produces_ultrahdr_jpeg(tmp_path, sdr, hdr_tiff):
    out = tmp_path / "out.jpg"
    ok, log, warning = assembler.run(sdr, hdr_tiff, out)
    assert ok, log
    assert_valid_ultrahdr(out, log)
    assert warning is False  # GainMapMin must not be negative (Instagram rejects it)


def test_jpeg_pipeline_round_trip(tmp_path, sdr, hdr_tiff):
    first = tmp_path / "first.jpg"
    ok, log, _ = assembler.run(sdr, hdr_tiff, first)
    assert ok, log
    second = tmp_path / "second.jpg"
    ok, log, warning = assembler.run(sdr, first, second)  # existing gain-map JPEG as HDR input
    assert ok, log
    assert_valid_ultrahdr(second, log)
    assert warning is False


def test_invalid_hdr_jpeg_fails_cleanly(tmp_path, sdr):
    not_hdr = tmp_path / "plain.jpg"
    shutil.copy(sdr, not_hdr)  # a JPEG without any gain map
    ok, log, warning = assembler.run(sdr, not_hdr, tmp_path / "out.jpg")
    assert ok is False and warning is False
    assert log.splitlines()[-1].startswith("Error:")
