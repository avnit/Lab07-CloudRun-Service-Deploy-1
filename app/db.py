# =====================================================================
# INTENTIONALLY VULNERABLE CODE - LAB / SANDBOX USE ONLY.
# CM-0001 / CWE-89: search_items() builds SQL with an f-string.
# Reference fix: patches/CM-0001-sqli.diff
# =====================================================================
"""Database access for the watchlist.

Backend selection:
  * DB_HOST set   -> MySQL (Cloud Run: the `mysql` sidecar on 127.0.0.1:3306)
  * DB_HOST unset -> a local SQLite file (local dev, unit tests, and the
                     egress-less CodeMender sandbox, where no MySQL exists)

Queries are written once with `?` placeholders; _run() rewrites them to `%s`
for MySQL, so the same statement (and the same patch) works on both backends.

Tables:
  items    the catalog (was data/catalog.json -> "items")
  sources  where the fetcher looks + topic rules (was data/sources.json)
  meta     catalog metadata (generated_at, note)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Iterable, Optional, Sequence

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
CATALOG_FILE = os.path.join(DATA_DIR, "catalog.json")
DEFAULT_DB_PATH = os.path.join("data", "watchlist.db")

ITEM_COLUMNS = (
    "id, title, source, creator, topics, url, published_at, "
    "duration_seconds, description, is_example"
)

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS items ("
    "id VARCHAR(64) PRIMARY KEY, "
    "title VARCHAR(500) NOT NULL, "
    "source VARCHAR(32) NOT NULL, "
    "creator VARCHAR(255), "
    "topics VARCHAR(500) NOT NULL, "
    "url VARCHAR(1000) NOT NULL, "
    "published_at VARCHAR(32), "
    "duration_seconds INTEGER, "
    "description TEXT, "
    "is_example INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sources ("
    "kind VARCHAR(32) NOT NULL, "
    "sort_order INTEGER NOT NULL, "
    "label VARCHAR(255), "
    "value_text VARCHAR(1000), "
    "options_json TEXT, "
    "PRIMARY KEY (kind, sort_order))",
    "CREATE TABLE IF NOT EXISTS meta ("
    "meta_key VARCHAR(64) PRIMARY KEY, "
    "meta_value TEXT)",
)


# ----------------------------- connection ----------------------------------
def backend() -> str:
    return "mysql" if os.environ.get("DB_HOST") else "sqlite"


def get_db_path(db_path: Optional[str] = None) -> str:
    """Return the SQLite file path. Relative paths resolve from the app root."""
    path = db_path or os.environ.get("DB_PATH", DEFAULT_DB_PATH)
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return path


def _connect(db_path: Optional[str] = None):
    if backend() == "mysql":
        import pymysql  # imported lazily: the sandbox image has no PyMySQL

        return pymysql.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD", ""),
            database=os.environ.get("DB_NAME", "watchlist"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _run(conn, sql: str, params: Optional[Sequence[Any]] = None) -> list[dict]:
    """Execute one statement and return its rows as dicts.

    Write `?` for each bound parameter; it becomes `%s` on MySQL.
    """
    args: Any = tuple(params) if params else ()
    if backend() == "mysql":
        sql = sql.replace("?", "%s")
        args = args or None  # PyMySQL only %-formats when args is not None
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        rows = cur.fetchall() if cur.description else []
        return [dict(row) for row in rows]
    finally:
        cur.close()


def wait_for_db(timeout_seconds: float = 60.0) -> None:
    """Block until the database accepts connections (MySQL sidecar start-up)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            _connect().close()
            return
        except Exception:  # noqa: BLE001 - any driver error means "not ready yet"
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


# ----------------------------- schema + seed -------------------------------
def init_db(db_path: Optional[str] = None, reseed: bool = False) -> None:
    """Create the tables and load data/*.json into them.

    Existing rows are kept unless reseed=True (tests) or a table is empty
    (first start of a fresh MySQL sidecar).
    """
    conn = _connect(db_path)
    try:
        for statement in SCHEMA:
            _run(conn, statement)
        conn.commit()
        items_empty = _run(conn, "SELECT COUNT(*) AS n FROM items")[0]["n"] == 0
        sources_empty = _run(conn, "SELECT COUNT(*) AS n FROM sources")[0]["n"] == 0
    finally:
        conn.close()
    if reseed or sources_empty:
        with open(SOURCES_FILE, encoding="utf-8") as handle:
            replace_sources(json.load(handle), db_path)
    if reseed or items_empty:
        with open(CATALOG_FILE, encoding="utf-8") as handle:
            replace_catalog(json.load(handle), db_path)


def _source_rows(doc: dict) -> Iterable[tuple]:
    """Flatten the sources.json document into (kind, label, value, options)."""
    for topic in doc.get("topics", []):
        yield ("topic", topic, None, None)
    youtube = doc.get("youtube", {})
    for channel in youtube.get("channel_ids", []):
        yield ("youtube_channel_id", None, channel, None)
    for term in youtube.get("search_terms", []):
        yield ("youtube_search_term", None, term, None)
    if "max_results_per_query" in youtube:
        yield ("setting", "youtube.max_results_per_query",
               str(youtube["max_results_per_query"]), None)
    for feed in doc.get("podcasts", {}).get("feeds", []):
        yield ("podcast_feed", feed.get("name"), feed.get("rss"),
               json.dumps({"keep_all": bool(feed.get("keep_all"))}))
    for page in doc.get("websites", {}).get("pages", []):
        yield ("website_page", page.get("name"), page.get("url"),
               json.dumps({"link_selector": page.get("link_selector", "")}))
    for topic, patterns in doc.get("match", {}).items():
        if topic == "comment":
            continue
        for pattern in patterns:
            yield ("topic_pattern", topic, pattern, None)


def replace_sources(doc: dict, db_path: Optional[str] = None) -> int:
    """Replace the sources table with the contents of a sources.json document."""
    conn = _connect(db_path)
    try:
        _run(conn, "DELETE FROM sources")
        count = 0
        for count, (kind, label, value, options) in enumerate(_source_rows(doc), 1):
            _run(
                conn,
                "INSERT INTO sources (kind, sort_order, label, value_text, options_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, count, label, value, options),
            )
        conn.commit()
        return count
    finally:
        conn.close()


def get_sources(db_path: Optional[str] = None) -> dict:
    """Rebuild the sources.json document from the sources table."""
    conn = _connect(db_path)
    try:
        rows = _run(
            conn,
            "SELECT kind, label, value_text, options_json FROM sources ORDER BY sort_order",
        )
    finally:
        conn.close()
    doc: dict = {
        "topics": [],
        "youtube": {"channel_ids": [], "search_terms": []},
        "podcasts": {"feeds": []},
        "websites": {"pages": []},
        "match": {},
    }
    for row in rows:
        kind, label, value = row["kind"], row["label"], row["value_text"]
        options = json.loads(row["options_json"]) if row["options_json"] else {}
        if kind == "topic":
            doc["topics"].append(label)
        elif kind == "youtube_channel_id":
            doc["youtube"]["channel_ids"].append(value)
        elif kind == "youtube_search_term":
            doc["youtube"]["search_terms"].append(value)
        elif kind == "setting" and label == "youtube.max_results_per_query":
            doc["youtube"]["max_results_per_query"] = int(value)
        elif kind == "podcast_feed":
            doc["podcasts"]["feeds"].append({"name": label, "rss": value, **options})
        elif kind == "website_page":
            doc["websites"]["pages"].append({"name": label, "url": value, **options})
        elif kind == "topic_pattern":
            doc["match"].setdefault(label, []).append(value)
    return doc


def replace_catalog(catalog: dict, db_path: Optional[str] = None) -> int:
    """Replace the items table (and catalog metadata) with a catalog document."""
    items = catalog.get("items", [])
    conn = _connect(db_path)
    try:
        _run(conn, "DELETE FROM items")
        for item in items:
            _run(
                conn,
                f"INSERT INTO items ({ITEM_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"],
                    item.get("title", ""),
                    item.get("source", ""),
                    item.get("creator"),
                    json.dumps(item.get("topics", [])),
                    item.get("url", ""),
                    item.get("published_at"),
                    item.get("duration_seconds"),
                    item.get("description"),
                    1 if item.get("is_example") else 0,
                ),
            )
        _run(conn, "DELETE FROM meta")
        for key in ("generated_at", "note"):
            _run(conn, "INSERT INTO meta (meta_key, meta_value) VALUES (?, ?)",
                 (key, catalog.get(key)))
        conn.commit()
        return len(items)
    finally:
        conn.close()


def _to_item(row: dict) -> dict:
    item = dict(row)
    item["topics"] = json.loads(item["topics"]) if item.get("topics") else []
    item["is_example"] = bool(item.get("is_example"))
    return item


def get_catalog(db_path: Optional[str] = None) -> dict:
    """Return the catalog document the web app expects."""
    conn = _connect(db_path)
    try:
        rows = _run(conn, f"SELECT {ITEM_COLUMNS} FROM items ORDER BY published_at DESC, id")
        meta = {r["meta_key"]: r["meta_value"] for r in _run(conn, "SELECT meta_key, meta_value FROM meta")}
    finally:
        conn.close()
    return {
        "generated_at": meta.get("generated_at"),
        "note": meta.get("note"),
        "items": [_to_item(row) for row in rows],
    }


def search_items(source: str, db_path: Optional[str] = None) -> list[dict]:
    """Return the catalog items that come from one source (youtube, podcast, website)."""
    conn = _connect(db_path)
    try:
        # VULNERABLE (CWE-89): user input is interpolated into the SQL text.
        query = (
            f"SELECT {ITEM_COLUMNS} "
            f"FROM items WHERE source = '{source}' ORDER BY id"
        )
        rows = _run(conn, query)
        return [_to_item(row) for row in rows]
    finally:
        conn.close()
