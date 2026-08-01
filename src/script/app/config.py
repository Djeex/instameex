"""Shared constants for the HDR-to-Instagram web front."""
from pathlib import Path

# This file lives at <repo root>/src/script/app/config.py.
SRC_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = SRC_DIR.parent

TEMPLATES_DIR = SRC_DIR / "templates"
ASSETS_DIR = SRC_DIR / "assets"
JOBS_DIR = REPO_ROOT / "jobs"
VERSION = (REPO_ROOT / "VERSION").read_text().strip()

ALLOWED_SDR_EXT = {".jpg", ".jpeg"}
ALLOWED_HDR_EXT = {".jpg", ".jpeg", ".tif", ".tiff"}
TIFF_EXT = {".tif", ".tiff"}
MAX_CONTENT_LENGTH = 80 * 1024 * 1024  # 80 MB, uncompressed 32-bit float HDR TIFFs can be large

# Instagram's exact feed resolutions — width x height, keyed by label.
IG_RESOLUTIONS = {
    (1080, 1080): "1:1 square",
    (1080, 1350): "4:5 portrait",
    (1080, 566): "1.91:1 landscape",
}

CONVERT_TIMEOUT = 300  # seconds, applied to each external tool call in assembler.py

# The result page pings /heartbeat while open; a job whose last ping is
# older than HEARTBEAT_TIMEOUT is considered "left" and gets purged by the
# reaper thread. This survives page refreshes (pings resume) and doesn't
# depend on an unload event ever firing (tab kill, crash, lost network).
HEARTBEAT_TIMEOUT = 12  # seconds
REAPER_INTERVAL = 4  # seconds
