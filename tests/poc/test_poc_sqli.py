"""PoC for CM-0001 (CWE-89 SQL injection in app/db.py:search_items).

PASSES while the injection works; FAILS once the query is parameterized.
Local SQLite file built from the seed catalog only.
"""

import importlib.util
import unittest

from tests import SeededDbMixin
from app import db

HAS_FLASK = importlib.util.find_spec("flask") is not None
PAYLOAD = "' OR '1'='1"


class SqliPocTest(SeededDbMixin, unittest.TestCase):
    def test_injection_returns_rows_for_other_sources(self):
        rows = db.search_items(PAYLOAD)
        sources = {row["source"] for row in rows}
        self.assertGreater(
            len(sources), 1,
            "exploit blocked: injected source filter did not return other sources' rows",
        )


@unittest.skipUnless(HAS_FLASK, "flask not installed")
class SqliPocFlaskTest(SeededDbMixin, unittest.TestCase):
    def test_injection_via_http_route(self):
        from app.main import create_app

        client = create_app({"TESTING": True}).test_client()
        resp = client.get("/api/items", query_string={"source": PAYLOAD})
        self.assertEqual(resp.status_code, 200)
        sources = {row["source"] for row in resp.get_json()["items"]}
        self.assertGreater(len(sources), 1, "exploit blocked via HTTP route")


if __name__ == "__main__":
    unittest.main()
