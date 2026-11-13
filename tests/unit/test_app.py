"""Unit tests for legitimate behaviour of the watchlist backend.

These pass on the vulnerable code and on correctly patched code.
"""

import importlib.util
import json
import os
import unittest

from tests import APP_ROOT, SeededDbMixin
from app import db, notes, refresher

HAS_FLASK = importlib.util.find_spec("flask") is not None


def _load(name):
    with open(os.path.join(APP_ROOT, "data", name), encoding="utf-8") as handle:
        return json.load(handle)


class CatalogTest(SeededDbMixin, unittest.TestCase):
    def test_catalog_round_trips_through_the_database(self):
        seed = _load("catalog.json")
        catalog = db.get_catalog()
        self.assertEqual(catalog["generated_at"], seed["generated_at"])
        by_id = {item["id"]: item for item in catalog["items"]}
        self.assertEqual(set(by_id), {item["id"] for item in seed["items"]})
        for item in seed["items"]:
            self.assertEqual(by_id[item["id"]]["topics"], item["topics"])
            self.assertEqual(by_id[item["id"]]["url"], item["url"])

    def test_search_returns_only_the_requested_source(self):
        rows = db.search_items("youtube")
        self.assertGreater(len(rows), 0)
        self.assertEqual({row["source"] for row in rows}, {"youtube"})

    def test_unknown_source_returns_no_rows(self):
        self.assertEqual(db.search_items("carrier-pigeon"), [])

    def test_init_db_is_idempotent(self):
        before = len(db.get_catalog()["items"])
        db.init_db()
        self.assertEqual(len(db.get_catalog()["items"]), before)


class SourcesTest(SeededDbMixin, unittest.TestCase):
    def test_sources_round_trip_through_the_database(self):
        seed = _load("sources.json")
        doc = db.get_sources()
        self.assertEqual(doc["topics"], seed["topics"])
        self.assertEqual(doc["youtube"]["search_terms"], seed["youtube"]["search_terms"])
        self.assertEqual(doc["youtube"]["max_results_per_query"],
                         seed["youtube"]["max_results_per_query"])
        self.assertEqual(doc["podcasts"]["feeds"], seed["podcasts"]["feeds"])
        self.assertEqual(doc["websites"]["pages"], seed["websites"]["pages"])
        self.assertEqual(doc["match"],
                         {k: v for k, v in seed["match"].items() if k != "comment"})


class RefresherTest(SeededDbMixin, unittest.TestCase):
    FRESH = [{
        "id": "pod-fresh-1", "title": "Fresh Hermes episode", "source": "podcast",
        "creator": "Test Feed", "topics": ["Hermes"], "url": "https://example.org/ep1",
        "published_at": "2026-11-01", "duration_seconds": None, "description": "new",
    }]

    def test_refresh_replaces_the_catalog_with_fetched_items(self):
        seen = {}

        def collect(sources):
            seen["topics"] = sources["topics"]
            return self.FRESH

        self.assertEqual(refresher.refresh_once(collect=collect), 1)
        self.assertEqual(seen["topics"], ["Antigravity", "Hermes"])  # read from the DB
        catalog = db.get_catalog()
        self.assertEqual([item["id"] for item in catalog["items"]], ["pod-fresh-1"])
        self.assertNotEqual(catalog["generated_at"], "seed")
        self.assertEqual(refresher.status()["last_result"], "updated")

    def test_empty_fetch_keeps_the_existing_catalog(self):
        before = db.get_catalog()
        self.assertEqual(refresher.refresh_once(collect=lambda sources: []), 0)
        self.assertEqual(db.get_catalog(), before)

    def test_refresh_is_off_unless_an_interval_is_set(self):
        self.assertIsNone(refresher.start(0))


class NotesTest(unittest.TestCase):
    def test_read_existing_note(self):
        self.assertIn("Antigravity", notes.read_note("antigravity.md"))

    def test_missing_note_raises(self):
        with self.assertRaises(notes.NoteNotFound):
            notes.read_note("no-such-note.md")


@unittest.skipUnless(HAS_FLASK, "flask not installed")
class FlaskRoutesTest(SeededDbMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from app.main import create_app

        self.client = create_app({"TESTING": True}).test_client()

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_web_app_is_served(self):
        resp = self.client.get("/web/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Watch Next", resp.get_data(as_text=True))
        resp.close()

    def test_catalog_route(self):
        resp = self.client.get("/api/catalog")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.get_json()["items"]), 0)

    def test_sources_route(self):
        resp = self.client.get("/api/sources")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hermes", resp.get_json()["topics"])

    def test_items_route(self):
        resp = self.client.get("/api/items?source=podcast")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({row["source"] for row in resp.get_json()["items"]}, {"podcast"})

    def test_items_requires_source(self):
        self.assertEqual(self.client.get("/api/items").status_code, 400)

    def test_note_route(self):
        resp = self.client.get("/api/notes?file=hermes.md")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hermes", resp.get_data(as_text=True))

    def test_missing_note_is_404(self):
        self.assertEqual(self.client.get("/api/notes?file=nope.md").status_code, 404)


if __name__ == "__main__":
    unittest.main()
