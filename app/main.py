# =====================================================================
# INTENTIONALLY VULNERABLE CODE - LAB / SANDBOX USE ONLY.
# Routes expose CM-0001 (SQL injection) and CM-0002 (path traversal).
# Binds to 127.0.0.1 by default; set HOST to override.
# =====================================================================
"""Flask app: serves the static web app and the catalog API backed by MySQL."""
from __future__ import annotations

import logging
import os
from typing import Optional

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from app import db, notes, refresher

logger = logging.getLogger("watchlist")

WEB_DIR = os.path.join(db.BASE_DIR, "web")
WARNING_LINE = (
    "watchlist is INTENTIONALLY VULNERABLE (CM-0001 SQLi, CM-0002 path "
    "traversal). Lab/sandbox use only. Do not expose to untrusted networks."
)


def create_app(config: Optional[dict] = None) -> Flask:
    """Build the Flask app and make sure the database is created and seeded."""
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = None
    if config:
        app.config.update(config)

    logging.basicConfig(level=logging.INFO)
    logger.warning(WARNING_LINE)
    if db.backend() == "mysql":
        db.wait_for_db()
    db.init_db(app.config["DB_PATH"])
    logger.info("database backend: %s", db.backend())
    if not app.config.get("TESTING"):
        refresher.start(refresher.interval_from_env(), app.config["DB_PATH"])

    @app.get("/")
    def root():
        return redirect("/web/")

    @app.get("/web/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/web/<path:filename>")
    def web_asset(filename: str):
        return send_from_directory(WEB_DIR, filename)

    @app.get("/health")
    def health():
        return jsonify({
            "status": "ok",
            "service": "watchlist",
            "db": db.backend(),
            "refresh": refresher.status(),
        })

    @app.get("/api/catalog")
    def catalog():
        return jsonify(db.get_catalog(app.config["DB_PATH"]))

    @app.get("/api/sources")
    def sources():
        return jsonify(db.get_sources(app.config["DB_PATH"]))

    @app.get("/api/items")
    def items():
        source = request.args.get("source")
        if not source:
            return jsonify({"error": "missing 'source' query parameter"}), 400
        rows = db.search_items(source, app.config["DB_PATH"])
        return jsonify({"source": source, "items": rows})

    @app.get("/api/notes")
    def get_note():
        name = request.args.get("file")
        if not name:
            return jsonify({"error": "missing 'file' query parameter"}), 400
        try:
            text = notes.read_note(name)
        except notes.NoteNotFound:
            return jsonify({"error": "note not found"}), 404
        return Response(text, mimetype="text/plain")

    return app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    create_app().run(host=host, port=port)


if __name__ == "__main__":
    main()
