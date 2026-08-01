"""Upload validation: file extensions and Instagram's exact feed resolutions."""
from pathlib import Path

import tifffile
from PIL import Image, UnidentifiedImageError

from .config import ALLOWED_HDR_EXT, ALLOWED_SDR_EXT, IG_RESOLUTIONS, TIFF_EXT


def ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_tiff(filename: str) -> bool:
    return ext(filename) in TIFF_EXT


def sdr_ext_error(filename: str) -> str | None:
    if ext(filename) not in ALLOWED_SDR_EXT:
        return "The SDR file must be a .jpg/.jpeg."
    return None


def hdr_ext_error(filename: str) -> str | None:
    if ext(filename) not in ALLOWED_HDR_EXT:
        return "The HDR file must be a .jpg/.jpeg (existing gain map) or a 32-bit float .tif/.tiff."
    return None


def probe_dimensions(path: Path) -> tuple[int, int]:
    if is_tiff(path.name):
        try:
            with tifffile.TiffFile(path) as tif:
                page = tif.pages[0]
                return (page.imagewidth, page.imagelength)
        except Exception as e:
            raise ValueError(f"could not read TIFF dimensions ({e})") from e
    try:
        with Image.open(path) as img:
            return img.size
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"could not read image dimensions ({e})") from e


def instagram_resolution_error(
    sdr_path: Path, hdr_path: Path, ignore_ig_resolution: bool = False,
) -> str | None:
    """Returns an error message if the pair doesn't meet Instagram's feed
    requirements, otherwise None.

    The dimension-match check always applies: mismatched SDR/HDR
    dimensions misalign the gain map regardless of what platform the
    result is for. ignore_ig_resolution skips only the exact-match check
    against Instagram's own feed resolutions, for results meant for
    somewhere other than Instagram."""
    try:
        sdr_w, sdr_h = probe_dimensions(sdr_path)
        hdr_w, hdr_h = probe_dimensions(hdr_path)
    except ValueError as e:
        return f"Could not validate image dimensions: {e}."

    if (sdr_w, sdr_h) != (hdr_w, hdr_h):
        return (
            f"SDR ({sdr_w}x{sdr_h}) and HDR ({hdr_w}x{hdr_h}) must have identical "
            "dimensions, otherwise the gain map will misalign."
        )

    if not ignore_ig_resolution and (sdr_w, sdr_h) not in IG_RESOLUTIONS:
        allowed = ", ".join(f"{w}x{h} ({label})" for (w, h), label in IG_RESOLUTIONS.items())
        return f"Image is {sdr_w}x{sdr_h} — Instagram requires an exact match to one of: {allowed}."

    return None
