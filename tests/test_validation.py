import numpy as np
import pytest
import tifffile
from PIL import Image

from app import validation


def make_jpeg(path, size):
    Image.new("RGB", size, "gray").save(path, "JPEG")
    return path


def make_tiff(path, size):
    tifffile.imwrite(path, np.zeros((size[1], size[0], 3), dtype=np.float32))
    return path


@pytest.mark.parametrize("name,expected", [
    ("a.JPG", ".jpg"), ("a.b.tiff", ".tiff"), ("noext", ""), ("", ""),
])
def test_ext(name, expected):
    assert validation.ext(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("x.tif", True), ("x.TIFF", True), ("x.jpg", False), ("tif", False),
])
def test_is_tiff(name, expected):
    assert validation.is_tiff(name) is expected


@pytest.mark.parametrize("name,ok", [
    ("a.jpg", True), ("a.JPEG", True), ("a.tif", False), ("a.png", False), ("", False),
])
def test_sdr_ext_error(name, ok):
    assert (validation.sdr_ext_error(name) is None) is ok


@pytest.mark.parametrize("name,ok", [
    ("a.jpg", True), ("a.jpeg", True), ("a.tif", True), ("a.TIFF", True),
    ("a.png", False), ("a.avif", False), ("", False),
])
def test_hdr_ext_error(name, ok):
    assert (validation.hdr_ext_error(name) is None) is ok


def test_probe_dimensions_jpeg_and_tiff(tmp_path):
    assert validation.probe_dimensions(make_jpeg(tmp_path / "a.jpg", (30, 20))) == (30, 20)
    assert validation.probe_dimensions(make_tiff(tmp_path / "a.tif", (30, 20))) == (30, 20)


def test_probe_dimensions_corrupt(tmp_path):
    bad_jpg = tmp_path / "bad.jpg"
    bad_jpg.write_bytes(b"not an image")
    bad_tif = tmp_path / "bad.tif"
    bad_tif.write_bytes(b"not a tiff")
    with pytest.raises(ValueError, match="image dimensions"):
        validation.probe_dimensions(bad_jpg)
    with pytest.raises(ValueError, match="TIFF dimensions"):
        validation.probe_dimensions(bad_tif)


def test_probe_dimensions_missing_file(tmp_path):
    with pytest.raises(ValueError):
        validation.probe_dimensions(tmp_path / "missing.jpg")


@pytest.mark.parametrize("size", [(1080, 1080), (1080, 1350), (1080, 566)])
def test_resolution_ok_for_each_instagram_format(tmp_path, size):
    sdr = make_jpeg(tmp_path / "s.jpg", size)
    hdr = make_jpeg(tmp_path / "h.jpg", size)
    assert validation.instagram_resolution_error(sdr, hdr) is None


def test_resolution_ok_with_tiff_hdr(tmp_path):
    sdr = make_jpeg(tmp_path / "s.jpg", (1080, 1080))
    hdr = make_tiff(tmp_path / "h.tif", (1080, 1080))
    assert validation.instagram_resolution_error(sdr, hdr) is None


def test_resolution_mismatch_always_rejected(tmp_path):
    sdr = make_jpeg(tmp_path / "s.jpg", (1080, 1080))
    hdr = make_jpeg(tmp_path / "h.jpg", (1080, 1350))
    for ignore in (False, True):
        assert "identical" in validation.instagram_resolution_error(sdr, hdr, ignore)


def test_resolution_not_instagram(tmp_path):
    sdr = make_jpeg(tmp_path / "s.jpg", (100, 100))
    hdr = make_jpeg(tmp_path / "h.jpg", (100, 100))
    assert "Instagram requires" in validation.instagram_resolution_error(sdr, hdr)
    assert validation.instagram_resolution_error(sdr, hdr, ignore_ig_resolution=True) is None


def test_resolution_swapped_dimensions_rejected(tmp_path):
    sdr = make_jpeg(tmp_path / "s.jpg", (1350, 1080))
    hdr = make_jpeg(tmp_path / "h.jpg", (1350, 1080))
    assert validation.instagram_resolution_error(sdr, hdr) is not None


def test_resolution_unreadable_file(tmp_path):
    sdr = make_jpeg(tmp_path / "s.jpg", (1080, 1080))
    bad = tmp_path / "h.jpg"
    bad.write_bytes(b"")
    assert "Could not validate" in validation.instagram_resolution_error(sdr, bad)
