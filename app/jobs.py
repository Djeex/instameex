"""In-memory job registry and lifecycle (creation, heartbeat, reaping).

Single-process only: JOBS lives in this module's memory, so this assumes
one gunicorn worker (see Dockerfile). Multiple workers would each keep a
separate registry and requests would 404 depending on which one handled
them.
"""
import shutil
import threading
import time
from pathlib import Path

from .config import HEARTBEAT_TIMEOUT, JOBS_DIR, REAPER_INTERVAL

JOBS: dict[str, dict] = {}


def reset_jobs_dir() -> None:
    """Wipe any leftovers from a previous run (crash, forced restart) —
    the in-memory registry never survives a restart anyway, so orphaned
    job dirs on disk would otherwise sit there forever."""
    shutil.rmtree(JOBS_DIR, ignore_errors=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def new_job_dir(job_id: str) -> Path:
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def register(job_id: str, **fields) -> None:
    JOBS[job_id] = {**fields, "last_seen": time.time()}


def get(job_id: str) -> dict | None:
    return JOBS.get(job_id)


def touch(job_id: str) -> None:
    job = JOBS.get(job_id)
    if job:
        job["last_seen"] = time.time()


def discard_dir(job_dir: Path) -> None:
    shutil.rmtree(job_dir, ignore_errors=True)


def cleanup(job_id: str) -> None:
    JOBS.pop(job_id, None)
    discard_dir(JOBS_DIR / job_id)


def _reap_stale_jobs() -> None:
    while True:
        time.sleep(REAPER_INTERVAL)
        cutoff = time.time() - HEARTBEAT_TIMEOUT
        stale = [jid for jid, job in list(JOBS.items()) if job.get("last_seen", 0) < cutoff]
        for jid in stale:
            cleanup(jid)


def start_reaper() -> None:
    threading.Thread(target=_reap_stale_jobs, daemon=True).start()
