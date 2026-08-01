"""Route handlers — wires the HTTP layer to jobs/validation/assembler."""
import io
import uuid
import zipfile

from flask import abort, redirect, render_template, request, send_file, url_for

from . import assembler, jobs, validation


def _process_pair(job_dir, index, sdr_file, hdr_file, ignore_ig_resolution=False):
    """Runs one SDR/HDR pair through validation + assembly. Returns an item
    dict for the job report; never raises — failures are recorded in it."""
    name = hdr_file.filename or sdr_file.filename or f"pair {index}"

    if not sdr_file.filename or not hdr_file.filename:
        return {"name": name, "success": False, "warning": False, "output": None,
                "log": "Missing SDR or HDR file for this pair."}

    ext_error = validation.sdr_ext_error(sdr_file.filename) or validation.hdr_ext_error(hdr_file.filename)
    if ext_error:
        return {"name": name, "success": False, "warning": False, "output": None, "log": ext_error}

    sdr_path = job_dir / f"sdr_{index}{validation.ext(sdr_file.filename)}"
    hdr_path = job_dir / f"hdr_{index}{validation.ext(hdr_file.filename)}"
    out_path = job_dir / f"instagram_hdr_output_{index}.jpg"

    sdr_file.save(sdr_path)
    hdr_file.save(hdr_path)

    ig_error = validation.instagram_resolution_error(sdr_path, hdr_path, ignore_ig_resolution)
    if ig_error:
        for p in (sdr_path, hdr_path):
            p.unlink(missing_ok=True)
        return {"name": name, "success": False, "warning": False, "output": None, "log": ig_error}

    success, log, warning = assembler.run(sdr_path, hdr_path, out_path)
    for p in (sdr_path, hdr_path):
        p.unlink(missing_ok=True)

    return {
        "name": name,
        "success": success,
        "warning": warning,
        "output": str(out_path) if success else None,
        "log": log,
    }


def register_routes(app):
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/convert")
    def convert():
        sdr_files = request.files.getlist("sdr[]")
        hdr_files = request.files.getlist("hdr[]")

        if not sdr_files or not hdr_files:
            return render_template("index.html", error="Add at least one SDR/HDR pair."), 400
        if len(sdr_files) != len(hdr_files):
            return render_template("index.html", error="Each pair needs both an SDR and an HDR file."), 400

        ignore_ig_resolution = request.form.get("ignore_ig_resolution") == "on"

        job_id = uuid.uuid4().hex[:12]
        job_dir = jobs.new_job_dir(job_id)

        items = [
            _process_pair(job_dir, i, sdr_file, hdr_file, ignore_ig_resolution)
            for i, (sdr_file, hdr_file) in enumerate(zip(sdr_files, hdr_files), start=1)
        ]

        jobs.register(job_id, items=items)
        return redirect(url_for("result", job_id=job_id))

    @app.get("/result/<job_id>")
    def result(job_id):
        job = jobs.get(job_id)
        if not job:
            abort(404)
        items = job["items"]
        ok_count = sum(1 for item in items if item["success"])
        total_count = len(items)
        if ok_count == total_count and total_count == 1:
            heading = "JPEG assembled"
        elif ok_count == total_count:
            heading = f"All {total_count} assembled"
        elif ok_count == 0:
            heading = "Conversion failed"
        else:
            heading = f"{ok_count}/{total_count} assembled"
        return render_template(
            "result.html",
            job_id=job_id,
            items=items,
            ok_count=ok_count,
            total_count=total_count,
            heading=heading,
        )

    @app.get("/download/<job_id>")
    def download(job_id):
        job = jobs.get(job_id)
        if not job:
            abort(404)
        successes = [item for item in job["items"] if item["success"] and item["output"]]
        if not successes:
            abort(404)

        if len(successes) == 1:
            return send_file(successes[0]["output"], as_attachment=True, download_name="instagram_hdr_output.jpg")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, item in enumerate(successes, start=1):
                zf.write(item["output"], arcname=f"instagram_hdr_output_{i}.jpg")
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="instagram_hdr_outputs.zip", mimetype="application/zip")

    @app.post("/heartbeat/<job_id>")
    def heartbeat(job_id):
        # Pinged by the result page while it's open/visible. Silently
        # ignored for unknown/already-reaped job_ids — nothing to keep alive.
        jobs.touch(job_id)
        return ("", 204)

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("index.html", error="File too large (max 80 MB)."), 413
