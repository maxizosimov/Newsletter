import json
import sqlite3
from urllib.parse import urlparse

import numpy as np

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    domain TEXT,
    status TEXT NOT NULL DEFAULT 'active',      -- active | candidate | muted
    origin TEXT NOT NULL DEFAULT 'seed',        -- seed | discovered
    added TEXT,
    status_changed TEXT,
    last_fetched TEXT,
    last_error TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    snippet TEXT,
    publisher TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_id INTEGER REFERENCES sources(id),
    published TEXT NOT NULL,
    fetched TEXT NOT NULL,
    embedding BLOB,
    story_id INTEGER REFERENCES stories(id)
);
CREATE INDEX IF NOT EXISTS items_story ON items(story_id);
CREATE INDEX IF NOT EXISTS items_published ON items(published);
CREATE INDEX IF NOT EXISTS items_domain ON items(domain);
-- Outbound links: which sites an item points readers to. Feeds discovery and "deep" grades.
CREATE TABLE IF NOT EXISTS links (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    PRIMARY KEY (item_id, domain)
);
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY,
    centroid BLOB NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    n_items INTEGER NOT NULL DEFAULT 0,
    headline TEXT,
    kicker TEXT,
    summary TEXT,
    layer TEXT,
    lens TEXT,
    kind TEXT,
    scope TEXT,                                  -- core | adjacent | offtopic
    importance INTEGER,
    status TEXT,
    enriched_n INTEGER NOT NULL DEFAULT 0,
    umbrella_id INTEGER REFERENCES umbrellas(id)
);
CREATE TABLE IF NOT EXISTS umbrellas (
    id INTEGER PRIMARY KEY,
    centroid BLOB NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    n_stories INTEGER NOT NULL DEFAULT 0,
    kicker TEXT,
    headline TEXT,
    why TEXT,
    seed_text TEXT,                              -- the founding story; matches are judged against it
    written_n INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS outlets (
    domain TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prior REAL NOT NULL,
    fast REAL NOT NULL,
    deep REAL NOT NULL,
    n_items INTEGER NOT NULL,
    n_multi INTEGER NOT NULL,
    n_early INTEGER NOT NULL,
    cited_by INTEGER NOT NULL,
    updated TEXT NOT NULL
);
-- Model launches pulled out of release stories, for the Models page.
CREATE TABLE IF NOT EXISTS releases (
    story_id INTEGER PRIMARY KEY REFERENCES stories(id) ON DELETE CASCADE,
    is_model INTEGER NOT NULL,
    provider TEXT,
    model TEXT,
    open_weights INTEGER,
    modality TEXT,
    what TEXT,
    checked_n INTEGER NOT NULL
);
-- Latest snapshot of Hugging Face's trending models, minus quantized re-uploads.
CREATE TABLE IF NOT EXISTS hf_trending (
    rank INTEGER PRIMARY KEY,
    model_id TEXT NOT NULL,
    org TEXT NOT NULL,
    likes INTEGER,
    downloads INTEGER,
    trending REAL,
    task TEXT,
    created TEXT,
    fetched TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discovery (
    domain TEXT PRIMARY KEY,
    mentions INTEGER NOT NULL,
    citers INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    tried_at TEXT,
    result TEXT
);
"""


# Columns added after a table first shipped; the database on the data branch gets them on next run.
MIGRATIONS = [
    ("umbrellas", "seed_text", "TEXT"),
    ("stories", "interest", "REAL"),
    ("stories", "triaged_n", "INTEGER NOT NULL DEFAULT 0"),
]


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, column, kind in MIGRATIONS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    return conn


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def sync_sources(conn: sqlite3.Connection, now: str) -> None:
    """Make the seed file the source of truth for seeded sources."""
    seeds = json.loads(config.SOURCES_FILE.read_text())
    for s in seeds:
        domain = s.get("domain") or (None if s["kind"] == "aggregator" else domain_of(s["url"]))
        conn.execute(
            "INSERT INTO sources (name, url, kind, domain, origin, added) VALUES (?, ?, ?, ?, 'seed', ?) "
            "ON CONFLICT(url) DO UPDATE SET name = excluded.name, kind = excluded.kind, domain = excluded.domain",
            (s["name"], s["url"], s["kind"], domain, now),
        )
    conn.commit()
