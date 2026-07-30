#!/usr/bin/env python3
"""
Instagram HDR Assembler — Web Front
------------------------------------
Flask front end for assembling Instagram-compliant HDR JPEGs (gain map
injection adapted from kostis-kounadis/instagram-hdr-assembler — see
LICENSE). Gives you a browser form instead of a terminal, and
surfaces the assembly report (including the "GainMapMin is negative"
warning) on a results page.

This file is just the entry point — see app/ for the app itself:
  app/config.py       constants
  app/jobs.py         in-memory job registry + heartbeat/reaper
  app/validation.py   upload + Instagram resolution checks
  app/assembler.py    gain-map assembly pipeline
  app/routes.py       Flask routes

Run directly:      python3 main.py
Run in Docker:      see Dockerfile (gunicorn main:app)
"""
import os
import sys

from app import create_app
from app.assembler import check_dependencies

app = create_app()

if __name__ == "__main__":
    missing = check_dependencies()
    if missing:
        print(f"ERROR: missing required tools on PATH: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
