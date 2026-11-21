import io
import zipfile

import pytest
from PIL import Image

from app import assembler, jobs


def jpeg_bytes(size=(1080, 1080)):
    buf = io.BytesIO()
    Image.new("RGB", size, "gray").save(buf, "JPEG")
    return buf.getvalue()


def pair(name="a", sdr_name=None, hdr_name=None, size=(1080, 1080)):
    return (
        (io.BytesIO(jpeg_bytes(size)), sdr_name or f"{name}_sdr.jpg"),
        (io.BytesIO(jpeg_bytes(size)), hdr_name or f"{name}_hdr.jpg"),
    )


def post(client, pairs):
    data = {"sdr[]": [p[0] for p in pairs], "hdr[]": [p[1] for p in pairs]}
    return client.post("/convert", data=data, content_type="multipart/form-data")


@pytest.fixture
def fake_run(monkeypatch):
    def run(sdr_path, hdr_path, out_path):
        out_path.write_bytes(b"OUT:" + out_path.name.encode())
        return True, "ok", False

    monkeypatch.setattr(assembler, "run", run)


def job_id_from(resp):
    return resp.headers["Location"].rstrip("/").split("/")[-1]


def test_index(client):
    assert client.get("/").status_code == 200


def test_convert_without_files(client):
    resp = client.post("/convert", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400 and b"at least one" in resp.data


def test_convert_unbalanced_pairs(client):
    data = {"sdr[]": [(io.BytesIO(jpeg_bytes()), "a.jpg")], "hdr[]": []}
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_convert_success_single(client, fake_run):
    resp = post(client, [pair()])
    assert resp.status_code == 302
    jid = job_id_from(resp)
    page = client.get(f"/result/{jid}")
    assert page.status_code == 200 and b"JPEG assembled" in page.data
    dl = client.get(f"/download/{jid}")
    assert dl.status_code == 200
    assert dl.headers["Content-Disposition"].endswith("instagram_hdr_output.jpg")
    assert dl.data.startswith(b"OUT:")


def test_convert_multiple_downloads_zip(client, fake_run):
    jid = job_id_from(post(client, [pair("a"), pair("b"), pair("c")]))
    assert b"All 3 assembled" in client.get(f"/result/{jid}").data
    dl = client.get(f"/download/{jid}")
    assert dl.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(dl.data)) as zf:
        assert zf.namelist() == [f"instagram_hdr_output_{i}.jpg" for i in (1, 2, 3)]


def test_partial_failure_download_only_successes(client, fake_run):
    bad = pair("b", sdr_name="b.png")
    jid = job_id_from(post(client, [pair("a"), bad]))
    assert b"1/2 assembled" in client.get(f"/result/{jid}").data
    dl = client.get(f"/download/{jid}")
    assert dl.mimetype != "application/zip"  # a single success is sent as a plain JPEG


def test_all_failed(client, fake_run):
    jid = job_id_from(post(client, [pair(sdr_name="x.png")]))
    assert b"Conversion failed" in client.get(f"/result/{jid}").data
    assert client.get(f"/download/{jid}").status_code == 404


def test_bad_hdr_extension_reported(client, fake_run):
    jid = job_id_from(post(client, [pair(hdr_name="h.png")]))
    assert jobs.get(jid)["items"][0]["success"] is False
    assert "HDR file" in jobs.get(jid)["items"][0]["log"]


@pytest.mark.parametrize("sdr_name,hdr_name", [("", "h.jpg"), ("s.jpg", ""), ("", "")])
def test_empty_filename_reported(tmp_path, sdr_name, hdr_name):
    from types import SimpleNamespace

    from app.routes import _process_pair

    item = _process_pair(tmp_path, 1, SimpleNamespace(filename=sdr_name),
                         SimpleNamespace(filename=hdr_name))
    assert item["success"] is False and "Missing" in item["log"]


def test_resolution_rejected_and_inputs_removed(client, fake_run, jobs_dir):
    jid = job_id_from(post(client, [pair(size=(100, 100))]))
    item = jobs.get(jid)["items"][0]
    assert not item["success"] and "Instagram requires" in item["log"]
    assert list((jobs_dir / jid).iterdir()) == []


def test_ignore_ig_resolution_flag(client, fake_run):
    pairs = [pair(size=(100, 100))]
    data = {"sdr[]": [pairs[0][0]], "hdr[]": [pairs[0][1]], "ignore_ig_resolution": "on"}
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert jobs.get(job_id_from(resp))["items"][0]["success"] is True


def test_assembler_failure_has_no_output(client, monkeypatch):
    monkeypatch.setattr(assembler, "run", lambda *a: (False, "boom", False))
    jid = job_id_from(post(client, [pair()]))
    item = jobs.get(jid)["items"][0]
    assert item["success"] is False and item["output"] is None
    assert client.get(f"/download/{jid}").status_code == 404


def test_unknown_job_404(client):
    assert client.get("/result/nope").status_code == 404
    assert client.get("/download/nope").status_code == 404


def test_heartbeat(client):
    assert client.post("/heartbeat/unknown").status_code == 204
    jobs.register("j1")
    jobs.JOBS["j1"]["last_seen"] = 0
    assert client.post("/heartbeat/j1").status_code == 204
    assert jobs.JOBS["j1"]["last_seen"] > 0


def test_too_large(client, monkeypatch):
    client.application.config["MAX_CONTENT_LENGTH"] = 10
    resp = client.post("/convert", data={"sdr[]": (io.BytesIO(b"x" * 100), "a.jpg")},
                       content_type="multipart/form-data")
    assert resp.status_code == 413 and b"too large" in resp.data
