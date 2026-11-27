"""Turn the database into the data the page shows: storylines, their angles, momentum and sources."""

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from . import config
from .ingest import now_utc
from .triage import passes

BUCKET_HOURS = 6


def coverage_bonus(n_outlets: int) -> int:
    return (n_outlets >= 5) + (n_outlets >= 15)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def build(conn: sqlite3.Connection) -> dict:
    now = now_utc()
    cutoff = now - timedelta(hours=config.WINDOW_HOURS)
    outlets = {r["domain"]: r for r in conn.execute("SELECT * FROM outlets")}
    on_probation = {r[0] for r in conn.execute("SELECT id FROM sources WHERE status = 'candidate'")}

    stories = conn.execute(
        "SELECT * FROM stories WHERE last_seen >= ? AND enriched_n > 0 AND scope != 'offtopic'",
        (cutoff.isoformat(),),
    ).fetchall()
    items_by_story = defaultdict(list)
    if stories:
        marks = ",".join("?" * len(stories))
        for i in conn.execute(f"SELECT * FROM items WHERE story_id IN ({marks}) ORDER BY published",
                              [s["id"] for s in stories]):
            items_by_story[i["story_id"]].append(i)
    umbrellas = {u["id"]: u for u in conn.execute(
        "SELECT * FROM umbrellas WHERE last_seen >= ?", (cutoff.isoformat(),))}

    def deep(i):
        o = outlets.get(i["domain"])
        return o["deep"] if o else config.DEFAULT_OUTLET_PRIOR

    def link(i):
        return {"publisher": i["publisher"], "title": i["title"], "url": i["url"], "time": i["published"][:16]}

    groups = defaultdict(list)
    for s in stories:
        items = items_by_story[s["id"]]
        # A story from sources on probation alone stays hidden until another source picks it up.
        if not items or all(i["source_id"] in on_probation for i in items):
            continue
        domains = {i["domain"] for i in items}
        # Same gate as the write-up step: only interesting or widely covered stories are shown.
        if s["triaged_n"] and not passes(s["interest"] or 0, s["scope"], len(domains)):
            continue
        best = max(items, key=lambda i: (deep(i), -datetime.fromisoformat(i["published"]).timestamp()))
        # A story not yet placed in a storyline stands alone (negative id keeps the keys apart).
        groups[s["umbrella_id"] or -s["id"]].append({
            "row": s, "items": items, "domains": domains,
            "view": {
                "kicker": s["kicker"], "headline": s["headline"], "summary": s["summary"],
                "outlets": len(domains), "best": link(best), "layer": s["layer"],
            },
        })

    result = []
    for uid, members in groups.items():
        members.sort(key=lambda m: len(m["domains"]), reverse=True)
        lead = members[0]["row"]
        u = umbrellas.get(uid)
        items = sorted((i for m in members for i in m["items"]), key=lambda i: i["published"])
        domains = {i["domain"] for i in items}
        importance = max(m["row"]["importance"] or 1 for m in members)
        size = min(5, importance + coverage_bonus(len(domains)))

        # Momentum: how many outlets joined the story in each 6-hour slot of the window.
        n_buckets = config.WINDOW_HOURS // BUCKET_HOURS
        buckets = [0] * n_buckets
        seen = set()
        for i in items:
            if i["domain"] in seen:
                continue
            seen.add(i["domain"])
            age_h = (now - datetime.fromisoformat(i["published"])).total_seconds() / 3600
            buckets[max(0, n_buckets - 1 - int(max(age_h, 0) // BUCKET_HOURS))] += 1
        rising = sum(buckets[-2:])

        last_seen = datetime.fromisoformat(max(i["published"] for i in items))
        age_h = max(0.0, (now - last_seen).total_seconds() / 3600)

        first = items[0]
        best = max(items, key=lambda i: (deep(i), -datetime.fromisoformat(i["published"]).timestamp()))
        statuses = {m["row"]["status"] for m in members}
        written = u is not None and u["written_n"] > 0 and len(members) > 1
        layer_votes = defaultdict(int)
        for m in members:
            layer_votes[m["row"]["layer"]] += len(m["domains"])
        result.append({
            "id": uid,
            "kicker": (u["kicker"] if written else lead["kicker"]) or lead["headline"],
            "headline": (u["headline"] if written else lead["headline"]) or "",
            "why": (u["why"] if written else lead["summary"]) or "",
            "layer": max(layer_votes, key=layer_votes.get),
            "lenses": sorted({m["row"]["lens"] for m in members if m["row"]["lens"]}),
            "kinds": sorted({m["row"]["kind"] for m in members if m["row"]["kind"]}),
            "scope": "core" if any(m["row"]["scope"] == "core" for m in members) else "adjacent",
            "status": "confirmed" if "confirmed" in statuses else ("claimed" if "claimed" in statuses else "rumor"),
            "size": size,
            "outlets": len(domains),
            "rising": rising,
            "momentum": buckets,
            "_interest": max(m["row"]["interest"] or m["row"]["importance"] or 1 for m in members),
            "_fresh": 0.5 + 0.5 * math.exp(-age_h / 36),
            "first_seen": first["published"][:16],
            "last_seen": iso(last_seen),
            "broke": {**link(first), "fast": round(outlets[first["domain"]]["fast"], 2) if first["domain"] in outlets else None},
            "best": link(best),
            "angles": [m["view"] for m in members],
            "coverage": [link(i) for i in reversed(items)][:80],
        })
    # Every story that survives triage is "interesting", so absolute scores bunch up. Size is a rank
    # instead: interest and coverage combined, then a fixed share of storylines per size.
    for r in result:
        r["_score"] = 0.5 * (r.pop("_interest") - 1) / 4 + 0.5 * min(1.0, math.log1p(r["outlets"]) / math.log1p(40))
    shares = [(0.05, 5), (0.15, 4), (0.35, 3), (0.65, 2)]
    ranked = sorted(result, key=lambda r: r["_score"], reverse=True)
    for i, r in enumerate(ranked):
        pct = i / max(1, len(ranked))
        r["size"] = next((size for cut, size in shares if pct < cut), 1)
        r["heat"] = round((r["size"] + 0.5 * math.log2(1 + r["outlets"]) + 0.3 * min(r["rising"], 10)) * r.pop("_fresh"), 3)
        del r["_score"]
    result.sort(key=lambda r: r["heat"], reverse=True)

    models = build_models(conn, outlets)
    triaged = conn.execute("SELECT COUNT(*) FROM stories WHERE last_seen >= ? AND triaged_n > 0",
                           (cutoff.isoformat(),)).fetchone()[0]
    week = (now - timedelta(days=7)).isoformat()
    graded = conn.execute("SELECT * FROM outlets WHERE n_items >= 3").fetchall()
    return {
        "generated": iso(now),
        "window_hours": config.WINDOW_HOURS,
        "bucket_hours": BUCKET_HOURS,
        "layers": [{"key": k, "name": v, "hint": config.LAYER_HINTS[k]} for k, v in config.LAYERS.items()],
        "storylines": result,
        "filtered": max(0, triaged - sum(len(groups[g]) for g in groups)),
        "models": models,
        "sources": {
            "active": conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'active'").fetchone()[0],
            "probation": [r[0] for r in conn.execute(
                "SELECT name FROM sources WHERE status = 'candidate' ORDER BY added DESC")],
            "promoted": [r[0] for r in conn.execute(
                "SELECT name FROM sources WHERE origin = 'discovered' AND status = 'active' AND status_changed >= ?", (week,))],
            "muted": [r[0] for r in conn.execute(
                "SELECT name FROM sources WHERE status = 'muted' AND status_changed >= ?", (week,))],
            "fastest": [r["name"] for r in sorted((g for g in graded if g["n_multi"] >= 3),
                                                  key=lambda g: g["fast"], reverse=True)[:6]],
            "deepest": [r["name"] for r in sorted(graded, key=lambda g: g["deep"], reverse=True)[:6]],
            "outlets": len({c["publisher"] for s in result for c in s["coverage"]}),
        },
    }


def build_models(conn: sqlite3.Connection, outlets: dict) -> dict:
    since = (now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT r.*, s.first_seen, s.kicker FROM releases r JOIN stories s ON s.id = r.story_id "
        "WHERE r.is_model = 1 AND s.first_seen >= ? ORDER BY s.first_seen", (since,),
    ).fetchall()

    def deep(i):
        o = outlets.get(i["domain"])
        return o["deep"] if o else config.DEFAULT_OUTLET_PRIOR

    # The same launch is often several stories (announcement, review, benchmarks): merge them.
    merged = {}
    for r in rows:
        key = (r["provider"], " ".join(r["model"].lower().replace("-", " ").split()))
        items = conn.execute("SELECT * FROM items WHERE story_id = ?", (r["story_id"],)).fetchall()
        m = merged.setdefault(key, {
            "provider": r["provider"], "model": r["model"], "open": bool(r["open_weights"]),
            "what": r["what"], "modality": r["modality"], "date": r["first_seen"][:16],
            "country": config.COUNTRY.get(r["provider"], ""), "items": [],
        })
        m["items"] += items
    releases = []
    for m in merged.values():
        items = m.pop("items")
        best = max(items, key=deep) if items else None
        m["outlets"] = len({i["domain"] for i in items})
        m["url"] = best["url"] if best else None
        m["source"] = best["publisher"] if best else None
        releases.append(m)
    releases.sort(key=lambda m: m["date"], reverse=True)

    closed = [m for m in releases if not m["open"]]
    frontier = [{"lab": lab, "country": config.COUNTRY.get(lab, ""),
                 "releases": [m for m in closed if m["provider"] == lab]} for lab in config.FRONTIER_LABS]
    other_closed = [m for m in closed if m["provider"] not in config.FRONTIER_LABS]
    # Labs with news first, most recent on top; quiet labs keep their fixed order below.
    frontier.sort(key=lambda l: l["releases"][0]["date"] if l["releases"] else "", reverse=True)

    trending = [{
        "rank": t["rank"], "id": t["model_id"], "org": t["org"], "name": t["model_id"].split("/", 1)[1],
        "likes": t["likes"], "downloads": t["downloads"], "score": t["trending"], "task": t["task"],
        "created": (t["created"] or "")[:16], "country": config.COUNTRY.get(t["org"].lower(), ""),
    } for t in conn.execute("SELECT * FROM hf_trending ORDER BY rank")]
    return {
        "window_days": config.MODELS_WINDOW_DAYS,
        "frontier": frontier,
        "other_closed": other_closed,
        "open": [m for m in releases if m["open"]],
        "trending": trending,
        "timeline": releases,
    }
