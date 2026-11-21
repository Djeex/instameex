import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "script"))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    from app import jobs

    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    jobs.JOBS.clear()
    yield tmp_path / "jobs"
    jobs.JOBS.clear()


@pytest.fixture
def client(jobs_dir, monkeypatch):
    from app import create_app, jobs

    monkeypatch.setattr(jobs, "start_reaper", lambda: None)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
