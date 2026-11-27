"""Turn the database into the data the page shows: storylines, their angles, momentum and sources."""

import math
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from . import config
from .db import from_blob
from .ingest import now_utc
from .triage import passes

BUCKET_HOURS = 6
# Each storyline links to this many others, the closest first, so the reader can keep going deeper.
DOORS = 12
DOORS_MIN = 4
# Below this similarity a link is only offered when it shares a named company, person or product.
# Measured after removing what all of today's stories have in common ("it's AI news").
DOOR_MIN_SIM = 0.30
DOOR_NAME_MIN_SIM = 0.10

NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*\b")
NOT_NAMES = {
    "AI", "The", "A", "An", "And", "Of", "In", "On", "For", "To", "With", "New", "How", "Why", "What",
    "Is", "Are", "As", "At", "By", "From", "Its", "It", "After", "Over", "Into", "More", "Than", "Says",
    "Report", "First", "Big", "Tech", "US", "U.S", "CEO", "Inc", "Model", "Models", "Data", "Open",
}


SENTENCE_START_RE = re.compile(r"(?:^|[.!?:]\s+|\s[-\u2014]\s)([A-Z][A-Za-z0-9]*)")


def names_in(text: str) -> set[str]:
    """Companies, people and products named in sentence-case text, a cheap stand-in for entities.
    A capitalised word only counts when it isn't just starting a sentence."""
    text = text or ""
    starts = {m.start(1) for m in SENTENCE_START_RE.finditer(text)}
    return {m.group() for m in NAME_RE.finditer(text)
            if m.start() not in starts and m.group() not in NOT_NAMES and len(m.group()) > 1
            and not m.group().startswith("AI-")}


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
        vecs = [from_blob(m["row"]["centroid"]) for m in members if m["row"]["centroid"]]
        vec = np.mean(vecs, axis=0) if vecs else None
        text = " ".join(m["row"]["summary"] or "" for m in members)
        result.append({
            "_vec": vec / (np.linalg.norm(vec) or 1) if vec is not None else None,
            "_names": names_in(text + " " + ((u["why"] or "") if written else "")),
            "_title_words": set(NAME_RE.findall(" ".join(m["row"]["kicker"] or "" for m in members))),
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
    link_doors(result)

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


def link_doors(storylines: list[dict]) -> None:
    """Give every storyline its closest neighbours, each with a short reason for the link."""
    # Headlines are in Title Case, so a capitalised headline word only counts as a name when some
    # summary also uses it as one.
    known = set().union(*(s["_names"] for s in storylines)) if storylines else set()
    for s in storylines:
        s["_names"] |= s.pop("_title_words") & known
    # Every story is AI news, so raw similarities are all high and a few broad stories look close to
    # everything. Subtracting the shared direction leaves what makes each story itself.
    with_vec = [s for s in storylines if s["_vec"] is not None]
    if with_vec:
        mean = np.mean([s["_vec"] for s in with_vec], axis=0)
        for s in with_vec:
            v = s["_vec"] - mean
            s["_vec"] = v / (np.linalg.norm(v) or 1)
    for s in storylines:
        options, fallback = [], []
        for o in storylines:
            if o is s or s["_vec"] is None or o["_vec"] is None:
                continue
            sim = float(s["_vec"] @ o["_vec"])
            fallback.append((sim, o["id"], "Closest topic"))
            shared = sorted(s["_names"] & o["_names"], key=len, reverse=True)
            # A shared name alone isn't enough when the stories are about different things.
            if sim < DOOR_MIN_SIM and (not shared or sim < DOOR_NAME_MIN_SIM):
                continue
            lens = set(s["lenses"]) & set(o["lenses"])
            score = sim + 0.15 * min(2, len(shared)) + 0.04 * (o["layer"] == s["layer"]) + 0.01 * min(o["heat"], 10)
            if shared:
                why = f"Also {shared[0]}"
            elif lens:
                why = f"More on {sorted(lens)[0]}"
            elif o["layer"] == s["layer"]:
                why = f"More in {config.LAYERS.get(o['layer'], 'this area')}"
            else:
                why = "Close topic"
            options.append((score, o["id"], why))
        options.sort(reverse=True)
        # Never a dead end: when few stories are close, the nearest others fill in.
        picked = options[:DOORS]
        taken = {i for _, i, _ in picked}
        picked += [f for f in sorted(fallback, reverse=True) if f[1] not in taken][:max(0, DOORS_MIN - len(picked))]
        s["doors"] = [{"id": i, "why": why} for _, i, why in picked]
    for s in storylines:
        del s["_vec"], s["_names"]


def launch_date(rows) -> str:
    """The first day two outlets agree on (within two days of each other), so one site with a
    wrong date can't move a launch a month early. A launch only one outlet covered keeps its date."""
    times = sorted({(datetime.fromisoformat(r["published"]), r["domain"] or r["publisher"]) for r in rows})
    for t, who in times:
        if any(o != who and timedelta(0) <= u - t <= timedelta(days=2) for u, o in times):
            return t.isoformat(timespec="minutes")[:16]
    return times[0][0].isoformat(timespec="minutes")[:16]


VERSION_RE = re.compile(r"^(.*?)[- ]?[A-Za-z]?(\d+)(?:\.\d+)*")


def drop_stale(releases: list[dict]) -> list[dict]:
    """Hide "launches" of an older major version after a newer one already shipped ("Opus 4.8"
    after "Opus 5.5"): those are old articles re-dated by a republishing site."""
    def parts(m):
        hit = VERSION_RE.match(m["model"])
        return (hit.group(1).strip().lower(), int(hit.group(2))) if hit else (m["model"].lower(), 0)
    keep = []
    for m in releases:
        fam, major = parts(m)
        if not any(parts(o)[0] == fam and parts(o)[1] > major and o["date"] < m["date"] for o in releases):
            keep.append(m)
    return keep


def build_models(conn: sqlite3.Connection, outlets: dict) -> dict:
    """Every tracked lab with its releases, newest first; the lab with the latest release on top."""
    labs = {lab["name"]: lab for lab in config.LABS}
    by_model = defaultdict(list)
    for r in conn.execute("SELECT * FROM launches ORDER BY published"):
        by_model[(r["provider"], r["model_key"])].append(r)

    def rank(r):
        # The lab's own post first, then the most trusted outlet, then whoever was earliest.
        own = any(r["domain"] == d or (r["domain"] or "").endswith("." + d) for d in labs[r["provider"]]["sites"])
        o = outlets.get(r["domain"])
        trust = o["deep"] if o else config.OUTLET_PRIOR.get(r["domain"], config.DEFAULT_OUTLET_PRIOR)
        return (own, trust, -datetime.fromisoformat(r["published"]).timestamp())

    releases = defaultdict(list)
    for (provider, key), rows in by_model.items():
        date = launch_date(rows)
        # The link comes from coverage of the launch itself, not from a site that dated it wrongly.
        near = [r for r in rows if abs(datetime.fromisoformat(r["published"]) - datetime.fromisoformat(date + ":00+00:00")) <= timedelta(days=3)]
        best = max(near or rows, key=rank)
        # The most common spelling is the name shown ("GPT-6.2 Sol", not "gpt-6.2 sol").
        names = defaultdict(int)
        for r in rows:
            names[r["model"]] += 1
        releases[provider].append({
            "key": f"{provider}|{key}", "model": max(names, key=names.get), "open": bool(best["open_weights"]),
            "date": date, "outlets": len({r["domain"] or r["publisher"] for r in rows}),
            "url": best["url"], "source": best["publisher"] or best["domain"], "headline": best["title"],
        })
    result = []
    for name in labs:
        rel = sorted(drop_stale(releases.get(name, [])), key=lambda m: m["date"], reverse=True)
        result.append({"lab": name, "country": config.COUNTRY.get(name, ""), "releases": rel,
                       "open": bool(rel) and all(m["open"] for m in rel)})
    result.sort(key=lambda l: l["releases"][0]["date"] if l["releases"] else "", reverse=True)

    trending = [{
        "rank": t["rank"], "id": t["model_id"], "org": t["org"], "name": t["model_id"].split("/", 1)[1],
        "likes": t["likes"], "downloads": t["downloads"], "score": t["trending"], "task": t["task"],
        "created": (t["created"] or "")[:16], "country": config.COUNTRY.get(t["org"].lower(), ""),
    } for t in conn.execute("SELECT * FROM hf_trending ORDER BY rank")]
    return {"labs": result, "trending": trending, "search_days": config.LAUNCH_SEARCH_DAYS}
