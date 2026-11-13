"""Keeps the catalog fresh: re-runs the fetcher on a timer inside the web process.

Why in-process: on Cloud Run the MySQL sidecar is only reachable from its own
instance (127.0.0.1), so an external job or scheduler cannot write to it. The
service keeps one instance with CPU always allocated, so a background thread
is enough. It also runs once at start-up, which matters because the sidecar's
database is empty after every deploy or restart.

Enable with REFRESH_INTERVAL_MINUTES > 0. Unset or 0 = disabled (the default
for local runs, tests and the egress-less sandbox).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import os
import threading
from typing import Callable, Optional

from app import db

logger = logging.getLogger("watchlist.refresher")

FETCHER_PATH = os.path.join(db.BASE_DIR, "scripts", "fetch_media.py")

_lock = threading.Lock()
_started = False
_status: dict = {
    "enabled": False,
    "interval_minutes": 0,
    "last_run_at": None,
    "last_result": "never run",
    "last_item_count": None,
}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_collector() -> Callable[[dict], list]:
    """Import scripts/fetch_media.py (not a package) and return collect_items."""
    spec = importlib.util.spec_from_file_location("fetch_media", FETCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.collect_items


def refresh_once(db_path: Optional[str] = None,
                 collect: Optional[Callable[[dict], list]] = None) -> int:
    """Fetch every source in the `sources` table and replace the catalog.

    If nothing is fetched (no API key, placeholder feeds, network down) the
    existing catalog is kept, so a failed run never empties the app.
    Returns the number of items fetched.
    """
    collect = collect or _load_collector()
    items = collect(db.get_sources(db_path))
    now = _utc_now()
    if items:
        db.replace_catalog(
            {
                "generated_at": now,
                "note": "Refreshed automatically by the background fetcher",
                "items": items,
            },
            db_path,
        )
        result = "updated"
    else:
        result = "no items fetched; kept the existing catalog"
    _status.update(last_run_at=now, last_result=result, last_item_count=len(items))
    logger.info("refresh: %s (%d items)", result, len(items))
    return len(items)


def _loop(interval_minutes: float, db_path: Optional[str], stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            refresh_once(db_path)
        except Exception as exc:  # noqa: BLE001 - never let the thread die
            _status.update(last_run_at=_utc_now(), last_result=f"error: {type(exc).__name__}")
            logger.exception("refresh failed")
        stop.wait(interval_minutes * 60)


def interval_from_env() -> float:
    try:
        return max(0.0, float(os.environ.get("REFRESH_INTERVAL_MINUTES", "0")))
    except ValueError:
        logger.warning("REFRESH_INTERVAL_MINUTES is not a number; auto-refresh disabled")
        return 0.0


def start(interval_minutes: float, db_path: Optional[str] = None) -> Optional[threading.Event]:
    """Start the refresh thread once per process. Returns its stop event."""
    global _started
    if interval_minutes <= 0:
        return None
    with _lock:
        if _started:
            return None
        _started = True
    _status.update(enabled=True, interval_minutes=interval_minutes)
    stop = threading.Event()
    threading.Thread(
        target=_loop, args=(interval_minutes, db_path, stop),
        name="catalog-refresher", daemon=True,
    ).start()
    logger.info("auto-refresh every %s minutes", interval_minutes)
    return stop


def status() -> dict:
    return dict(_status)
