"""HDR-to-Instagram web front — Flask app factory."""
from flask import Flask

from . import jobs
from .config import ASSETS_DIR, MAX_CONTENT_LENGTH, TEMPLATES_DIR, VERSION
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(ASSETS_DIR),
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    jobs.reset_jobs_dir()
    jobs.start_reaper()

    register_routes(app)

    @app.context_processor
    def inject_version():
        return {"app_version": VERSION}

    return app
