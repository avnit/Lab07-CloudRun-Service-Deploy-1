"""Tests for the watchlist lab app. Run from the repo root:

    python -m pytest -q tests/unit      # legitimate behaviour
    python -m pytest -q tests/poc       # PoCs: PASS while the app is exploitable

Tests never need MySQL. They force the SQLite backend and use one file,
data/test_watchlist.db (gitignored), re-seeded from data/*.json before each
test. Override its location with TEST_DB_PATH.
"""

import os
import sys

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


def seeded_db_path():
    return os.environ.get("TEST_DB_PATH") or os.path.join(APP_ROOT, "data", "test_watchlist.db")


class SeededDbMixin:
    """Force the SQLite backend, point DB_PATH at the test database, re-seed it."""

    def setUp(self):
        from app import db

        self._old_env = {k: os.environ.get(k) for k in ("DB_PATH", "DB_HOST")}
        os.environ.pop("DB_HOST", None)
        os.environ["DB_PATH"] = seeded_db_path()
        db.init_db(reseed=True)

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
