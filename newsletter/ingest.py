"""Fetch every active and probationary source and store new items plus their outbound links."""

import calendar
import html
import re
import sqlite3
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import httpx

from . import config
from .db import domain_of

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
HREF_RE = re.compile(r"""href=["'](https?://[^"'#\s>]+)""", re.I)
# Discovered sources are muted after this many failed fetches in a row.
MAX_FAILURES = 8


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean(text: str, limit: int = 400) -> str:
    text = SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()
    return text[:limit]


def entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc)


def outbound_domains(entry, own: str) -> set[str]:
    """Sites an article links to, e.g. a newsletter citing Reuters or a lab blog."""
    body = " ".join(c.get("value", "") for c in entry.get("content", [])) or entry.get("summary", "")
    found = {domain_of(u) for u in HREF_RE.findall(body)}
    return {d for d in found if d and d != own and not d.endswith("." + own) and "." in d}


def parse_feed(source: sqlite3.Row, body: bytes) -> list[dict]:
    feed = feedparser.parse(body)
    items = []
    for e in feed.entries:
        url = e.get("link")
        title = clean(e.get("title", ""), 300)
        if not url or not title:
            continue
        publisher, dom = source["name"], source["domain"] or domain_of(url)
        snippet = clean(e.get("summary", ""))
        links = outbound_domains(e, dom)
        if source["kind"] == "aggregator":
            # Credit the real outlet, not the aggregator, so coverage counts are honest.
            if "news.google.com" in source["url"]:
                src = e.get("source") or {}
                publisher = src.get("title") or "Google News"
                dom = domain_of(src.get("href", "")) or publisher.lower()
                suffix = f" - {publisher}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
            else:
                dom = domain_of(url)
                publisher = dom
            snippet = ""  # aggregator summaries are boilerplate
            # An aggregator surfacing a site counts as a mention of it, for discovery.
            links = {dom}
        items.append({
            "url": url, "title": title, "snippet": snippet, "publisher": publisher, "domain": dom,
            "published": entry_time(e) or now_utc(), "links": links,
        })
    return items


def fetch_hf_papers(client: httpx.Client, source: sqlite3.Row) -> list[dict]:
    r = client.get("https://huggingface.co/api/daily_papers", params={"limit": 100})
    r.raise_for_status()
    papers = sorted(r.json(), key=lambda p: p["paper"].get("upvotes", 0), reverse=True)
    return [{
        "url": f"https://huggingface.co/papers/{p['paper']['id']}",
        "title": clean(p["paper"]["title"], 300),
        "snippet": clean(p["paper"].get("summary", "")),
        "publisher": source["name"], "domain": source["domain"],
        "published": datetime.fromisoformat(p["publishedAt"].replace("Z", "+00:00")),
        "links": set(),
    } for p in papers[: config.HF_PAPERS_LIMIT]]


def fetch_source(client: httpx.Client, source: sqlite3.Row):
    try:
        if source["url"] == "hf:daily_papers":
            return source, fetch_hf_papers(client, source), None
        r = client.get(source["url"])
        r.raise_for_status()
        return source, parse_feed(source, r.content), None
    except Exception as e:  # one bad source must never stop the run
        return source, [], f"{type(e).__name__}: {e}"[:300]


def fetch_all(sources: list[sqlite3.Row]) -> list:
    """Different hosts in parallel; the same host one request at a time, so nobody gets hammered."""
    by_host = defaultdict(list)
    for s in sources:
        by_host[urlparse(s["url"]).netloc or s["url"]].append(s)

    def run_host(group):
        out = []
        for i, s in enumerate(group):
            if i:
                time.sleep(2)
            out.append(fetch_source(client, s))
        return out

    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        with ThreadPoolExecutor(max_workers=16) as pool:
            return [r for group in pool.map(run_host, by_host.values()) for r in group]


def prune(conn: sqlite3.Connection) -> None:
    keep = (now_utc() - timedelta(days=config.RETENTION_DAYS)).isoformat()
    window = (now_utc() - timedelta(hours=config.WINDOW_HOURS)).isoformat()
    conn.execute("DELETE FROM items WHERE published < ?", (keep,))
    # Vectors are only needed while a story can still grow.
    conn.execute("UPDATE items SET embedding = NULL WHERE published < ? AND embedding IS NOT NULL", (window,))
    conn.execute("DELETE FROM stories WHERE id NOT IN (SELECT DISTINCT story_id FROM items WHERE story_id IS NOT NULL)")
    conn.execute("DELETE FROM umbrellas WHERE id NOT IN (SELECT DISTINCT umbrella_id FROM stories WHERE umbrella_id IS NOT NULL)")


def run(conn: sqlite3.Connection) -> None:
    sources = conn.execute("SELECT * FROM sources WHERE status IN ('active', 'candidate')").fetchall()
    news_cutoff = now_utc() - timedelta(hours=config.WINDOW_HOURS)
    # Labs' own announcements are kept for the whole Models window, so releases show up even
    # on a first run, before the news window has had a chance to see them.
    lab_cutoff = now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)
    results = fetch_all(sources)

    fetched_at = now_utc().isoformat()
    added = failed = 0
    for source, items, error in results:
        if error:
            failed += 1
            print(f"  ! {source['name']}: {error[:120]}")
            conn.execute("UPDATE sources SET last_error = ?, fail_count = fail_count + 1 WHERE id = ?",
                         (error, source["id"]))
            if source["origin"] == "discovered" and source["fail_count"] + 1 >= MAX_FAILURES:
                conn.execute("UPDATE sources SET status = 'muted', status_changed = ? WHERE id = ?",
                             (fetched_at, source["id"]))
            continue
        conn.execute("UPDATE sources SET last_fetched = ?, last_error = NULL, fail_count = 0 WHERE id = ?",
                     (fetched_at, source["id"]))
        cutoff = lab_cutoff if source["kind"] == "primary" else news_cutoff
        for it in items:
            if it["published"] < cutoff:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO items (url, title, snippet, publisher, domain, source_id, published, fetched) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (it["url"], it["title"], it["snippet"], it["publisher"], it["domain"],
                 source["id"], it["published"].isoformat(), fetched_at),
            )
            if cur.rowcount:
                added += 1
                conn.executemany("INSERT OR IGNORE INTO links (item_id, domain) VALUES (?, ?)",
                                 [(cur.lastrowid, d) for d in it["links"]])
    prune(conn)
    conn.commit()
    print(f"ingest: {len(sources)} sources ({failed} failed), {added} new items")
