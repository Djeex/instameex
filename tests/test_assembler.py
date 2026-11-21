import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile
from PIL import Image

from app import assembler


def cp(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(assembler.shutil, "which", lambda t: f"/usr/bin/{t}")


def test_check_dependencies(monkeypatch):
    monkeypatch.setattr(assembler.shutil, "which", lambda t: None)
    assert assembler.check_dependencies() == ["ultrahdr_app", "exiftool"]
    monkeypatch.setattr(assembler.shutil, "which", lambda t: "/x" if t == "exiftool" else None)
    assert assembler.check_dependencies() == ["ultrahdr_app"]
    monkeypatch.setattr(assembler.shutil, "which", lambda t: "/x")
    assert assembler.check_dependencies() == []


@pytest.mark.parametrize("desc,code", [
    ("Display P3", "1"), ("Rec2020 PQ", "2"), ("ITU-R BT.2100", "2"),
    ("sRGB IEC61966-2.1", "0"), ("", "0"),
])
def test_detect_gamut(monkeypatch, tmp_path, desc, code):
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: cp(stdout=desc + "\n"))
    assert assembler._detect_gamut(tmp_path / "x.jpg") == code


def test_decode_hdr_intent_error(monkeypatch, tools, tmp_path):
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: cp(1, stderr="bad file"))
    with pytest.raises(assembler.AssemblyError, match="bad file"):
        assembler._decode_hdr_intent(tmp_path / "h.jpg", tmp_path / "o.raw")


def test_encode_without_and_with_max_boost(monkeypatch, tools, tmp_path):
    calls = []
    monkeypatch.setattr(assembler.subprocess, "run", lambda args, **k: calls.append(args) or cp())
    assembler._encode(tmp_path / "r", "0", tmp_path / "s", "0", 10, 20, tmp_path / "o")
    assert "-K" not in calls[0] and calls[0][calls[0].index("-t") + 1] == "1"

    assembler._encode(tmp_path / "r", "1", tmp_path / "s", "0", 10, 20, tmp_path / "o", max_boost=4.0)
    args = calls[1]
    assert args[args.index("-K") + 1] == "4.0"
    assert args[args.index("-k") + 1] == "1"  # floor never below 1
    assert args[args.index("-L") + 1] == str(4.0 * 203)


@pytest.mark.parametrize("boost,nits", [(0.1, 203), (100.0, 10000)])
def test_encode_target_nits_clamped(monkeypatch, tools, tmp_path, boost, nits):
    calls = []
    monkeypatch.setattr(assembler.subprocess, "run", lambda args, **k: calls.append(args) or cp())
    assembler._encode(tmp_path / "r", "0", tmp_path / "s", "0", 1, 1, tmp_path / "o", max_boost=boost)
    assert calls[0][calls[0].index("-L") + 1] == str(nits)


def test_encode_failure(monkeypatch, tools, tmp_path):
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: cp(1, stderr="nope"))
    with pytest.raises(assembler.AssemblyError, match="nope"):
        assembler._encode(tmp_path / "r", "0", tmp_path / "s", "0", 1, 1, tmp_path / "o")


def test_to_4_2_0_keeps_icc_profile(tmp_path):
    src, dest = tmp_path / "s.jpg", tmp_path / "d.jpg"
    Image.new("RGB", (16, 16), "red").save(src, "JPEG", icc_profile=b"ICCDATA")
    assembler._to_4_2_0(src, dest)
    with Image.open(dest) as img:
        assert img.info.get("icc_profile") == b"ICCDATA"
        assert img.size == (16, 16)


def test_to_4_2_0_without_icc(tmp_path):
    src, dest = tmp_path / "s.jpg", tmp_path / "d.jpg"
    Image.new("RGB", (8, 8)).save(src, "JPEG")
    assembler._to_4_2_0(src, dest)
    assert dest.exists()


def test_tiff_to_hdr_raw(tmp_path):
    tiff = tmp_path / "h.tif"
    data = np.full((2, 3, 3), 2.0, dtype=np.float32)
    data[0, 0] = -1.0  # negative values must be clipped
    tifffile.imwrite(tiff, data)
    dest = tmp_path / "out.raw"
    w, h, linear = assembler._tiff_to_hdr_raw(tiff, dest)
    assert (w, h) == (3, 2)
    assert linear[0, 0, 0] == 0.0
    assert linear[1, 1, 0] == pytest.approx(2.0 ** assembler._HLG_SYSTEM_GAMMA)
    assert dest.stat().st_size == 2 * 3 * 4 * 2  # RGBA half floats


def test_jpeg_to_linear_range(tmp_path):
    p = tmp_path / "w.jpg"
    Image.new("RGB", (4, 4), "white").save(p, "JPEG")
    lin = assembler._jpeg_to_linear(p)
    assert lin.shape == (4, 4, 3) and lin.max() == pytest.approx(1.0, abs=0.02)


def test_tiff_max_boost_ignores_near_black_and_picks_32nd(tmp_path):
    sdr = tmp_path / "s.jpg"
    Image.new("RGB", (16, 16), (128, 128, 128)).save(sdr, "JPEG", quality=100)
    sdr_lin = assembler._jpeg_to_linear(sdr)
    hdr = sdr_lin * 3.0
    assert assembler._tiff_max_boost(hdr, sdr) == pytest.approx(3.0, rel=0.01)
    hdr[0, 0] = 1000.0  # a lone spike must not set the boost
    assert assembler._tiff_max_boost(hdr, sdr) == pytest.approx(3.0, rel=0.01)


def test_tiff_max_boost_all_black_image_has_no_signal(tmp_path):
    sdr = tmp_path / "s.jpg"
    Image.new("RGB", (8, 8), "black").save(sdr, "JPEG")
    assert assembler._tiff_max_boost(np.ones((8, 8, 3), dtype=np.float32), sdr) == 1.0


def test_tiff_max_boost_fewer_than_32_pixels(tmp_path):
    sdr = tmp_path / "s.jpg"
    Image.new("RGB", (2, 2), (128, 128, 128)).save(sdr, "JPEG", quality=100)
    hdr = assembler._jpeg_to_linear(sdr) * 2.0
    assert assembler._tiff_max_boost(hdr, sdr) == pytest.approx(2.0, rel=0.01)


def test_probe_hdr_capacity(monkeypatch, tools, tmp_path):
    out = "foo\n  --hdrCapacityMax 3.5\n"
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: cp(stdout=out))
    assert assembler._probe_hdr_capacity(tmp_path / "x") == 3.5
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: cp(stdout="nothing"))
    with pytest.raises(assembler.AssemblyError):
        assembler._probe_hdr_capacity(tmp_path / "x")


def fake_exiftool(min_value=None, extract_ok=True, report_stdout=None):
    import json

    def run(args, **k):
        if "-MPImage2" in args:
            return cp(0 if extract_ok else 1, stdout=b"data" if extract_ok else b"")
        stdout = report_stdout
        if stdout is None:
            meta = {"XMP-hdrgm:Version": "1.0", "Other:Tag": "x"}
            if min_value is not None:
                meta["XMP-hdrgm:GainMapMin"] = min_value
            stdout = json.dumps([meta])
        return cp(stdout=stdout)

    return run


@pytest.mark.parametrize("value,negative", [(-0.5, True), (0, False), (1, False), (None, False)])
def test_validate_output_gain_map_min(monkeypatch, tmp_path, value, negative):
    monkeypatch.setattr(assembler.subprocess, "run", fake_exiftool(min_value=value))
    log = []
    assert assembler._validate_output(tmp_path / "o.jpg", log) is negative
    assert any("Validation report" in line for line in log)
    assert any("WARNING" in line for line in log) is negative
    assert not any("Other:Tag" in line for line in log)  # non-hdrgm tags filtered


@pytest.mark.parametrize("kwargs", [
    {"extract_ok": False}, {"report_stdout": "not json"}, {"report_stdout": "[]"},
])
def test_validate_output_unreadable_metadata(monkeypatch, tmp_path, kwargs):
    monkeypatch.setattr(assembler.subprocess, "run", fake_exiftool(**kwargs))
    log = []
    assert assembler._validate_output(tmp_path / "o.jpg", log) is False
    assert log == []


def test_run_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(assembler.shutil, "which", lambda t: None)
    ok, log, warn = assembler.run(tmp_path / "s.jpg", tmp_path / "h.jpg", tmp_path / "o.jpg")
    assert (ok, warn) == (False, False) and "ultrahdr_app" in log


@pytest.mark.parametrize("suffix,target", [
    (".jpg", "_assemble_from_jpeg"), (".JPEG", "_assemble_from_jpeg"),
    (".tif", "_assemble_from_tiff_hdr"), (".TIFF", "_assemble_from_tiff_hdr"),
])
def test_run_dispatch_by_hdr_extension(monkeypatch, tools, tmp_path, suffix, target):
    called = []
    for name in ("_assemble_from_jpeg", "_assemble_from_tiff_hdr"):
        monkeypatch.setattr(assembler, name, lambda *a, n=name: called.append(n))
    monkeypatch.setattr(assembler, "_validate_output", lambda *a: True)
    ok, log, warn = assembler.run(tmp_path / "s.jpg", tmp_path / f"h{suffix}", tmp_path / "o.jpg")
    assert called == [target] and ok is True and warn is True and "Done!" in log


@pytest.mark.parametrize("exc", [
    assembler.AssemblyError("boom"),
    subprocess.CalledProcessError(1, "x"),
    subprocess.TimeoutExpired("x", 1),
])
def test_run_pipeline_errors_are_reported(monkeypatch, tools, tmp_path, exc):
    def fail(*a):
        raise exc

    monkeypatch.setattr(assembler, "_assemble_from_jpeg", fail)
    ok, log, warn = assembler.run(tmp_path / "s.jpg", tmp_path / "h.jpg", tmp_path / "o.jpg")
    assert (ok, warn) == (False, False) and log.startswith("Error:")
