"""Find new sources without anyone curating a list.

Every article we read links to other sites, and aggregators surface outlets we don't follow.
A site that keeps getting cited by several of our sources becomes a candidate: we look for its
feed, let the local model check that it is actually about AI, and start it on probation.
"""

import re
import sqlite3
from datetime import timedelta
from urllib.parse import urljoin

import feedparser
import httpx

from . import config
from .ingest import now_utc
from .llm import ask_json, pick

FEED_LINK_RE = re.compile(r"<link[^>]+>", re.I)
COMMON_PATHS = ["/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml",
                "/blog/rss.xml", "/news/rss.xml", "/blog/feed"]

RELEVANCE_PROMPT = """Here are recent post titles from the website "{name}" ({domain}):

{titles}

Is this site mainly about AI, machine learning, chips/compute, or the business of AI and tech?
General news sites that only sometimes cover AI do NOT count.

Return JSON: {{"relevant": true or false, "kind": "news" (reporting), "analysis" (commentary,
newsletters, research blogs) or "primary" (a company or lab announcing its own work)}}"""


def feed_links(html: str, base: str) -> list[str]:
    out = []
    for tag in FEED_LINK_RE.findall(html):
        low = tag.lower()
        if "alternate" in low and ("rss+xml" in low or "atom+xml" in low):
            m = re.search(r"""href=["']([^"']+)""", tag, re.I)
            if m:
                out.append(urljoin(base, m.group(1)))
    return out


def find_feed(client: httpx.Client, domain: str):
    base = f"https://{domain}/"
    candidates = []
    try:
        r = client.get(base)
        if r.status_code == 200:
            candidates += feed_links(r.text[:200_000], str(r.url))
    except httpx.HTTPError:
        pass
    candidates += [urljoin(base, p) for p in COMMON_PATHS]
    for url in dict.fromkeys(candidates):
        try:
            r = client.get(url)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        feed = feedparser.parse(r.content)
        if len(feed.entries) >= 3:
            return str(r.url), feed
    return None, None


def candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    since = (now_utc() - timedelta(days=14)).isoformat()
    now = now_utc().isoformat()
    conn.execute(
        """INSERT INTO discovery (domain, mentions, citers, first_seen)
           SELECT l.domain, COUNT(DISTINCT l.item_id), COUNT(DISTINCT i.source_id), ?
           FROM links l JOIN items i ON i.id = l.item_id WHERE i.published >= ? GROUP BY l.domain
           ON CONFLICT(domain) DO UPDATE SET mentions = excluded.mentions, citers = excluded.citers""",
        (now, since),
    )
    tracked = {r[0] for r in conn.execute("SELECT domain FROM sources WHERE domain IS NOT NULL")}
    retry = (now_utc() - timedelta(days=14)).isoformat()
    rows = conn.execute(
        "SELECT * FROM discovery WHERE mentions >= ? AND citers >= ? AND (tried_at IS NULL OR tried_at < ?) "
        "ORDER BY citers DESC, mentions DESC",
        (config.DISCOVERY_MIN_MENTIONS, config.DISCOVERY_MIN_CITERS, retry),
    ).fetchall()
    return [r for r in rows if r["domain"] not in tracked
            and r["domain"] not in config.DISCOVERY_BLOCKLIST
            and not any(r["domain"].endswith("." + b) for b in config.DISCOVERY_BLOCKLIST
                        if b not in ("substack.com", "medium.com"))][: config.DISCOVERY_PER_RUN]


def run(conn: sqlite3.Connection) -> None:
    todo = candidates(conn)
    added = []
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
        for c in todo:
            now = now_utc().isoformat()
            url, feed = find_feed(client, c["domain"])
            if not url:
                result = "no feed"
            else:
                name = (feed.feed.get("title") or c["domain"]).strip()[:60]
                titles = "\n".join(f"- {e.get('title', '')}" for e in feed.entries[:10])
                try:
                    out = ask_json(RELEVANCE_PROMPT.format(name=name, domain=c["domain"], titles=titles))
                    relevant = out.get("relevant") is True or str(out.get("relevant")).lower() == "true"
                    kind = pick(out.get("kind"), ("news", "analysis", "primary"), "news")
                except Exception as e:
                    relevant, kind = False, "news"
                    print(f"  ! relevance {c['domain']}: {type(e).__name__}")
                if relevant and not conn.execute("SELECT 1 FROM sources WHERE url = ?", (url,)).fetchone():
                    conn.execute(
                        "INSERT INTO sources (name, url, kind, domain, status, origin, added, status_changed) "
                        "VALUES (?, ?, ?, ?, 'candidate', 'discovered', ?, ?)",
                        (name, url, kind, c["domain"], now, now),
                    )
                    added.append(name)
                    result = "added"
                else:
                    result = "not relevant" if not relevant else "duplicate"
            conn.execute("UPDATE discovery SET tried_at = ?, result = ? WHERE domain = ?",
                         (now, result, c["domain"]))
            conn.commit()
    print(f"discover: checked {len(todo)} sites, added {len(added)} on probation"
          + (f": {', '.join(added)}" if added else ""))
