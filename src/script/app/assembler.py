"""Assembles the final Instagram HDR JPEG from an SDR export + an HDR
JPEG that already carries a gain map (a Lightroom/Camera Raw HDR export).

Adapted from kostis-kounadis/instagram-hdr-assembler (MIT-licensed, see
LICENSE at the repo root). The upstream script also supported a Method 1
pipeline (decoding AVIF/TIFF into a dynamically generated gain map), but
app/validation.py only ever accepts a .jpg HDR export with an existing
gain map, so that path, and its quality/transfer/gamut knobs, was
dropped here.

A gain map only reconstructs a correct HDR image when it's applied to the
exact SDR base it was computed against. Lightroom's own HDR export bakes
its gain map against *its own* embedded base image, which is very often
not pixel-identical to a separately-exported SDR file, even from the
same edit (different sharpening, noise reduction, or color-space
rounding between export passes), and definitely not identical when the
SDR is a deliberately different edit. Reusing that gain map as-is against
a different SDR (the old approach) silently reconstructs the wrong HDR
appearance. Instead, this pipeline decodes the real HDR intent out of the
Lightroom file (undoing its own base and gain map), then recomputes a
fresh gain map against the user's actual SDR file, so the output's
visible base is exactly the provided SDR, and the gain map is the
correct one for reconstructing the original HDR intent from it.

The HDR side can optionally be a 32-bit float linear TIFF instead of a
gain-map JPEG (Lightroom's HDR TIFF export, 1.0 = SDR reference white).
This skips the JPEG gain-map JPEG entirely, so there's no 8-bit-in-8-bit
precision ceiling and no JPEG-compression noise inflating near-black
pixels into meaningless outlier ratios; the real per-pixel HDR/SDR ratio
is used directly. The SDR side stays a normal JPEG export either way,
matching how Lightroom's own HDR export plugins do it (SDR JPEG as base,
a separate TIFF only for the HDR intent) and avoiding having to
re-derive a viewable, correctly color-managed JPEG from linear TIFF
data ourselves.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from .config import CONVERT_TIMEOUT, TIFF_EXT

REQUIRED_TOOLS = ("ultrahdr_app", "exiftool")


class AssemblyError(Exception):
    """A pipeline step failed; the message is shown on the result page."""


def check_dependencies() -> list[str]:
    """Returns the names of any required external tool missing from PATH."""
    return [tool for tool in REQUIRED_TOOLS if not shutil.which(tool)]


def _decode_hdr_intent(hdr_path: Path, dest: Path) -> None:
    """Decodes the real (linear) HDR pixel data out of a gain-map JPEG,
    undoing its own embedded base + gain map."""
    ultrahdr_app = shutil.which("ultrahdr_app")
    result = subprocess.run(
        [ultrahdr_app, "-m", "1", "-j", str(hdr_path), "-z", str(dest)],
        capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
    )
    if result.returncode != 0:
        raise AssemblyError(
            "Could not decode HDR intent from the provided file "
            f"(not a valid HDR JPEG with an embedded gain map?): {result.stderr.strip()}"
        )


def _detect_gamut(path: Path) -> str:
    """Best-effort mapping from the embedded ICC profile to ultrahdr_app's
    gamut codes. ultrahdr_app cross-checks the -c/-C value it's given
    against the ICC box for compressed JPEG inputs and errors out on a
    mismatch, so a wide-gamut export (Display P3, Rec.2020) needs the
    right code passed explicitly, defaults to bt709/sRGB otherwise."""
    result = subprocess.run(
        ["exiftool", "-ICC_Profile:ProfileDescription", "-s3", str(path)],
        capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
    )
    description = result.stdout.strip().lower()
    if "2020" in description or "2100" in description:
        return "2"  # bt2100
    if "p3" in description:
        return "1"  # p3
    return "0"  # bt709 / sRGB


def _strip_xmp(path: Path) -> None:
    subprocess.run(
        ["exiftool", "-xmp:all=", str(path), "-overwrite_original", "-q"],
        check=False, timeout=CONVERT_TIMEOUT,
    )


def _to_4_2_0(src: Path, dest: Path) -> None:
    """Re-encodes as a baseline JPEG with 4:2:0 chroma subsampling,
    which ultrahdr_app requires for both the SDR and the gain map. Pillow
    doesn't carry the source's ICC profile over on save unless it's passed
    back in explicitly, which would silently flatten wide-gamut exports
    (Display P3, Rec.2020) to sRGB."""
    with Image.open(src) as img:
        icc_profile = img.info.get("icc_profile")
        img.convert("RGB").save(
            dest, format="JPEG", quality=95, subsampling=2, icc_profile=icc_profile
        )


def _encode(
    hdr_raw: Path, hdr_gamut: str, sdr_420: Path, sdr_gamut: str,
    width: int, height: int, out_path: Path,
    max_boost: float | None = None,
    hdr_transfer: str = "1", hdr_format: str = "5",
) -> None:
    """Recomputes a fresh gain map between the raw HDR intent and the
    given SDR base, and packages both into the final UltraHDR JPEG.

    hdr_transfer/hdr_format describe how hdr_raw is encoded: defaults
    (hlg, rgba1010102) match _decode_hdr_intent's output for the JPEG
    pipeline; the TIFF pipeline passes (linear, rgbahalffloat) instead.

    Without max_boost, ultrahdr_app fits the gain map's 8-bit code space to
    the actual min/max HDR-to-SDR ratio found in the image. A handful of
    near-black SDR pixels (JPEG noise, crushed shadows) can have a ratio
    hundreds of times larger than every other pixel, which stretches that
    8-bit range to cover them and leaves barely any precision for the
    ratios that actually matter, visible as flattened contrast and lost
    detail. Passing max_boost clamps the code space to the real,
    meaningful range instead.

    The floor is always 1 (no pixel is ever dimmed below its SDR value),
    never max_boost's reciprocal: Instagram rejects (silently falls back
    to plain SDR) files with a negative GainMapMin, which is what a
    sub-1 floor produces. A few pixels that would ideally be dimmed a
    little just render at their SDR brightness in HDR mode instead,
    which is a much smaller loss than Instagram dropping HDR entirely.

    max_boost also sets -L (target display peak brightness in nits),
    which is what hdrCapacityMax is derived from (nits / 203, the SDR
    reference white ultrahdr_app assumes). Without it, -L keeps its
    fixed default (1000 nits for hlg, 10000 for linear) regardless of
    the image, so hdrCapacityMax ends up as a generic constant instead
    of reflecting how much boost this file actually needs. Viewers that
    auto-scale the applied boost against hdrCapacityMax (rather than
    just showing maxContentBoost outright) under-apply the gain map
    when that constant overstates the real requirement, the highlights
    look barely boosted even though the gain map data itself is fine."""
    ultrahdr_app = shutil.which("ultrahdr_app")
    args = [
        ultrahdr_app, "-m", "0",
        "-p", str(hdr_raw), "-i", str(sdr_420),
        "-w", str(width), "-h", str(height),
        "-t", hdr_transfer, "-a", hdr_format,
        "-C", hdr_gamut, "-c", sdr_gamut,
        "-z", str(out_path),
    ]
    if max_boost is not None:
        target_nits = min(max(max_boost * 203, 203), 10000)
        args += ["-K", str(max_boost), "-k", "1", "-L", str(target_nits)]
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
    )
    if result.returncode != 0:
        raise AssemblyError(f"ultrahdr_app failed:\n{result.stderr}")


# HLG's nominal system gamma (ITU-R BT.2100), the OOTF exponent that maps
# scene light to display light for a reference viewing environment.
_HLG_SYSTEM_GAMMA = 1.2


def _tiff_to_hdr_raw(tiff_path: Path, dest: Path) -> tuple[int, int, np.ndarray]:
    """Converts a linear HDR intent TIFF into the RGBA half-float raw
    buffer ultrahdr_app expects for a raw HDR input. Returns the
    dimensions and the source array, the latter reused to compute the
    real boost range needed directly from the floats.

    The TIFF's values are scene-linear (1.0 = SDR reference white), but
    ultrahdr_app's "-t 0" (linear) mode treats -p as already
    display-referred and applies no OOTF of its own, unlike "-t 1" (hlg),
    which the JPEG pipeline uses and which carries HLG's OOTF built in.
    Skipping it here left shadows visibly brighter and highlights
    slightly under-boosted compared to Lightroom's own HLG-based gain
    map, confirmed by comparing decoded values against it in both a dark
    and a bright region: applying scene_linear ** gamma before encoding
    matched Lightroom's own numbers far more closely in both."""
    linear = tifffile.imread(tiff_path)
    display_linear = np.power(np.clip(linear, 0, None), _HLG_SYSTEM_GAMMA)
    height, width, _ = display_linear.shape
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[:, :, :3] = display_linear
    rgba[:, :, 3] = 1.0
    rgba.astype(np.float16).tofile(dest)
    return width, height, display_linear


def _jpeg_to_linear(path: Path) -> np.ndarray:
    """Decodes a JPEG to approximate linear light values (inverse sRGB
    EOTF), so it can be compared directly against a TIFF's linear pixel
    data. Only used to estimate a sane boost-clamp range, not for color
    output, so treating any SDR gamut's transfer curve as sRGB-shaped is
    close enough."""
    with Image.open(path) as img:
        arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return np.where(arr <= 0.04045, arr / 12.92, np.power((arr + 0.055) / 1.055, 2.4))


def _tiff_max_boost(hdr_linear: np.ndarray, sdr_420: Path) -> float:
    """The real per-pixel HDR/SDR ratio needed, computed from the source
    TIFF floats directly rather than probed back out of an encoded gain
    map. Pixels where the SDR is near-black are excluded: JPEG
    compression noise there can produce a ratio hundreds of times larger
    than anywhere else in the image, without reflecting real content.

    Everywhere else keeps its true ratio, but the true max alone is too
    sensitive to a handful of pixels (a 4:2:0 subsampling/DCT artifact
    right at a sharp edge can spike a couple of pixels far above
    everything else). A genuine highlight (a light source, a reflection)
    spans a real cluster of pixels, not a handful, so the 32nd-highest
    ratio is used instead of the true max: high enough to still capture
    small real highlights, past the point a few-pixel artifact reaches."""
    sdr_linear = _jpeg_to_linear(sdr_420)
    real_signal = sdr_linear > 0.005
    ratio = hdr_linear[real_signal] / sdr_linear[real_signal]
    n = min(32, ratio.size)
    return float(np.partition(ratio, -n)[-n])


def _probe_hdr_capacity(path: Path) -> float:
    """Reads back the natural (unclamped) hdrCapacityMax ultrahdr_app
    computed for an already-encoded UltraHDR JPEG."""
    result = subprocess.run(
        [shutil.which("ultrahdr_app"), "-m", "1", "-j", str(path), "-P"],
        capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
    )
    for line in result.stdout.splitlines():
        if line.strip().startswith("--hdrCapacityMax"):
            return float(line.split()[1])
    raise AssemblyError("Could not read back gain map metadata after encoding.")


def _validate_output(out_path: Path, log: list[str]) -> bool:
    """Appends the gain-map report to log; returns True if GainMapMin is
    negative (the known symptom Instagram may reject the file for)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gainmap = Path(tmpdir) / "gainmap.jpg"
        extract = subprocess.run(
            ["exiftool", "-b", "-MPImage2", str(out_path)],
            capture_output=True, timeout=CONVERT_TIMEOUT,
        )
        if extract.returncode != 0 or not extract.stdout:
            return False
        gainmap.write_bytes(extract.stdout)

        report = subprocess.run(
            ["exiftool", "-j", "-G1", "-XMP-hdrgm:all", str(gainmap)],
            capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
        )
        if report.returncode != 0:
            return False
        try:
            metadata = json.loads(report.stdout)[0]
        except (json.JSONDecodeError, IndexError, KeyError):
            return False

    log.append("--- Validation report ---")
    for key, value in metadata.items():
        if "hdrgm" in key.lower() or "gainmap" in key.lower():
            log.append(f"{key}: {value}")

    gain_map_min = metadata.get("XMP-hdrgm:GainMapMin")
    negative = gain_map_min is not None and float(gain_map_min) < 0
    if negative:
        log.append(
            "WARNING: GainMapMin is negative. Instagram may reject this file. "
            "Try adjusting HDR export settings in Camera Raw."
        )
    return negative


def _assemble_from_jpeg(sdr_path: Path, hdr_path: Path, out_path: Path, log: list[str], tmp: Path) -> None:
    log.append("Decoding HDR intent from the HDR source...")
    hdr_raw = tmp / "hdr_intent.raw"
    _decode_hdr_intent(hdr_path, hdr_raw)
    hdr_gamut = _detect_gamut(hdr_path)

    with Image.open(hdr_path) as hdr_img:
        width, height = hdr_img.size

    sdr_clean = tmp / "sdr.jpg"
    shutil.copy2(sdr_path, sdr_clean)
    log.append("Cleaning SDR XMP...")
    _strip_xmp(sdr_clean)
    log.append("Converting SDR to 4:2:0 subsampling...")
    sdr_420 = tmp / "sdr_420.jpg"
    _to_4_2_0(sdr_clean, sdr_420)
    sdr_gamut = _detect_gamut(sdr_420)

    log.append("Recomputing gain map against the SDR...")
    probe_path = tmp / "probe.jpg"
    _encode(hdr_raw, hdr_gamut, sdr_420, sdr_gamut, width, height, probe_path)
    hdr_capacity = _probe_hdr_capacity(probe_path)

    log.append("Encoding the final ISO UltraHDR JPEG...")
    _encode(
        hdr_raw, hdr_gamut, sdr_420, sdr_gamut, width, height, out_path,
        max_boost=hdr_capacity,
    )


def _assemble_from_tiff_hdr(sdr_path: Path, hdr_path: Path, out_path: Path, log: list[str], tmp: Path) -> None:
    """Same idea as _assemble_from_jpeg, but the HDR intent comes straight
    from Lightroom's linear HDR TIFF export instead of being decoded back
    out of a gain-map JPEG. The SDR side is still a normal JPEG export,
    handled exactly like the all-JPEG pipeline: mirrors how Lightroom's
    own HDR export plugins do it (real SDR JPEG as base, separate TIFF
    only for the HDR intent), and avoids re-deriving a viewable JPEG
    (and its color-managed transfer curve) from linear TIFF data
    ourselves."""
    log.append("Reading linear HDR intent from the TIFF...")
    hdr_raw = tmp / "hdr_intent.raw"
    width, height, hdr_linear = _tiff_to_hdr_raw(hdr_path, hdr_raw)
    hdr_gamut = _detect_gamut(hdr_path)

    sdr_clean = tmp / "sdr.jpg"
    shutil.copy2(sdr_path, sdr_clean)
    log.append("Cleaning SDR XMP...")
    _strip_xmp(sdr_clean)
    log.append("Converting SDR to 4:2:0 subsampling...")
    sdr_420 = tmp / "sdr_420.jpg"
    _to_4_2_0(sdr_clean, sdr_420)
    sdr_gamut = _detect_gamut(sdr_420)

    max_boost = _tiff_max_boost(hdr_linear, sdr_420)

    log.append("Encoding the final ISO UltraHDR JPEG...")
    _encode(
        hdr_raw, hdr_gamut, sdr_420, sdr_gamut, width, height, out_path,
        max_boost=max_boost, hdr_transfer="0", hdr_format="4",
    )


def run(sdr_path: Path, hdr_path: Path, out_path: Path) -> tuple[bool, str, bool]:
    """Assembles the HDR JPEG. Returns (success, log, gain_map_warning)."""
    log: list[str] = []
    missing = check_dependencies()
    if missing:
        return False, f"Error: missing required tools on PATH: {', '.join(missing)}", False

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            if hdr_path.suffix.lower() in TIFF_EXT:
                _assemble_from_tiff_hdr(sdr_path, hdr_path, out_path, log, tmp)
            else:
                _assemble_from_jpeg(sdr_path, hdr_path, out_path, log, tmp)

        warning = _validate_output(out_path, log)
        log.append(f"Done! HDR JPEG created at: {out_path}")
        return True, "\n".join(log), warning

    except (AssemblyError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.append(f"Error: {e}")
        return False, "\n".join(log), False
