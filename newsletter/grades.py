"""Grade every outlet on two separate axes, from its own track record over the last 30 days.

fast: how often it is among the first to report a story that others then cover.
deep: how trustworthy a full read it is, a prior by source type, nudged up by how many other
      sources link to it (outlets that others cite tend to be the ones doing original work).

Also runs probation: discovered sources get promoted once they prove on-topic, or muted.
"""

import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import config
from .ingest import now_utc

EARLY_RANK = 2           # among the first two outlets on a story
EARLY_MINUTES = 60       # or within an hour of the first report
MULTI_OUTLETS = 3        # only stories with real pickup say anything about speed


def priors(conn: sqlite3.Connection) -> dict[str, float]:
    p = dict(config.OUTLET_PRIOR)
    for s in conn.execute("SELECT domain, kind FROM sources WHERE domain IS NOT NULL AND kind != 'aggregator'"):
        p[s["domain"]] = config.KIND_DEPTH[s["kind"]]
    return p


def grade(conn: sqlite3.Connection) -> int:
    since = (now_utc() - timedelta(days=config.RETENTION_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT domain, publisher, story_id, published FROM items WHERE published >= ?", (since,)
    ).fetchall()
    names = defaultdict(Counter)
    n_items = Counter()
    first_by_story = defaultdict(dict)  # story -> domain -> earliest time
    for r in rows:
        names[r["domain"]][r["publisher"]] += 1
        n_items[r["domain"]] += 1
        if r["story_id"]:
            t = datetime.fromisoformat(r["published"])
            cur = first_by_story[r["story_id"]].get(r["domain"])
            if cur is None or t < cur:
                first_by_story[r["story_id"]][r["domain"]] = t

    n_multi, n_early = Counter(), Counter()
    for by_domain in first_by_story.values():
        if len(by_domain) < MULTI_OUTLETS:
            continue
        ordered = sorted(by_domain.items(), key=lambda kv: kv[1])
        start = ordered[0][1]
        for rank, (dom, t) in enumerate(ordered):
            n_multi[dom] += 1
            if rank < EARLY_RANK or (t - start).total_seconds() <= EARLY_MINUTES * 60:
                n_early[dom] += 1

    # Who links to whom, counting each citing outlet once and never an outlet citing itself.
    cited = Counter()
    for r in conn.execute(
        "SELECT l.domain AS target, COUNT(DISTINCT i.domain) AS n FROM links l JOIN items i ON i.id = l.item_id "
        "WHERE i.published >= ? AND l.domain != i.domain GROUP BY l.domain", (since,)
    ):
        cited[r["target"]] = r["n"]

    prior = priors(conn)
    now = now_utc().isoformat()
    conn.execute("DELETE FROM outlets")
    for dom, count in n_items.items():
        p = prior.get(dom, config.DEFAULT_OUTLET_PRIOR)
        evidence = min(1.0, math.log1p(cited[dom]) / math.log1p(15))
        conn.execute(
            "INSERT INTO outlets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dom, names[dom].most_common(1)[0][0], p,
             (n_early[dom] + 0.5) / (n_multi[dom] + 2),       # smoothed toward 25%
             0.7 * p + 0.3 * evidence,
             count, n_multi[dom], n_early[dom], cited[dom], now),
        )
    return len(n_items)


def probation(conn: sqlite3.Connection) -> tuple[int, int]:
    now = now_utc()
    promoted = muted = 0
    for s in conn.execute("SELECT * FROM sources WHERE status = 'candidate'").fetchall():
        age = now - datetime.fromisoformat(s["added"])
        on_topic = conn.execute(
            "SELECT COUNT(*) FROM items i JOIN stories st ON st.id = i.story_id "
            "WHERE i.source_id = ? AND st.scope IN ('core', 'adjacent')", (s["id"],),
        ).fetchone()[0]
        if on_topic >= config.PROMOTE_MIN_ITEMS and age >= timedelta(days=2):
            new = "active"
            promoted += 1
        elif age >= timedelta(days=config.PROBATION_DAYS):
            new = "muted"
            muted += 1
        else:
            continue
        conn.execute("UPDATE sources SET status = ?, status_changed = ? WHERE id = ?",
                     (new, now.isoformat(), s["id"]))
    return promoted, muted


def run(conn: sqlite3.Connection) -> None:
    n = grade(conn)
    promoted, muted = probation(conn)
    conn.commit()
    print(f"grades: {n} outlets graded, {promoted} sources promoted, {muted} muted")
