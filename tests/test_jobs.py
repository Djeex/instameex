import time

import pytest

from app import jobs


def test_new_job_dir_creates_directory(jobs_dir):
    d = jobs.new_job_dir("abc")
    assert d == jobs_dir / "abc" and d.is_dir()
    assert jobs.new_job_dir("abc") == d  # idempotent


def test_register_get_unknown(jobs_dir):
    assert jobs.get("nope") is None
    jobs.register("j1", items=[1])
    job = jobs.get("j1")
    assert job["items"] == [1] and "last_seen" in job


def test_touch_updates_and_ignores_unknown(jobs_dir):
    jobs.register("j1")
    jobs.JOBS["j1"]["last_seen"] = 0
    jobs.touch("j1")
    assert jobs.JOBS["j1"]["last_seen"] > 0
    jobs.touch("unknown")  # must not raise
    assert "unknown" not in jobs.JOBS


def test_cleanup_removes_registry_and_dir(jobs_dir):
    d = jobs.new_job_dir("j1")
    (d / "f.txt").write_text("x")
    jobs.register("j1")
    jobs.cleanup("j1")
    assert jobs.get("j1") is None and not d.exists()


def test_cleanup_unknown_job_is_noop(jobs_dir):
    jobs.reset_jobs_dir()
    jobs.cleanup("ghost")


def test_reset_jobs_dir_wipes_leftovers(jobs_dir):
    jobs.new_job_dir("old")
    jobs.reset_jobs_dir()
    assert jobs_dir.is_dir() and list(jobs_dir.iterdir()) == []


def test_reap_removes_only_stale_jobs(jobs_dir, monkeypatch):
    jobs.new_job_dir("stale")
    jobs.new_job_dir("fresh")
    jobs.register("stale")
    jobs.register("fresh")
    jobs.JOBS["stale"]["last_seen"] = time.time() - 1000

    def stop(_):
        if stop.called:
            raise StopIteration
        stop.called = True

    stop.called = False
    monkeypatch.setattr(jobs.time, "sleep", stop)
    with pytest.raises(StopIteration):
        jobs._reap_stale_jobs()
    assert "stale" not in jobs.JOBS and not (jobs_dir / "stale").exists()
    assert "fresh" in jobs.JOBS and (jobs_dir / "fresh").exists()


def test_reap_with_no_jobs(jobs_dir, monkeypatch):
    calls = []

    def stop(_):
        if calls:
            raise StopIteration
        calls.append(1)

    monkeypatch.setattr(jobs.time, "sleep", stop)
    with pytest.raises(StopIteration):
        jobs._reap_stale_jobs()
