"""Group related stories into storylines ("umbrellas") and write one explanation for each.

Embeddings propose which storylines a story might belong to; the model decides, because
"same company" is not the same as "same saga" (an xAI lawsuit is not part of Nvidia's CEO drama).
"""

import sqlite3
from datetime import timedelta

import numpy as np

from . import config
from .db import from_blob, to_blob
from .ingest import now_utc
from .llm import ask_json, clamp_int

MATCH_PROMPT = """A news story arrived. Decide whether it is part of one of the ongoing storylines below.

New story: {story}

Storylines:
{options}

A story belongs to a storyline only if it is about the same specific event or saga: the same
named people or companies AND the same underlying development (including reactions, consequences
and follow-ups). Sharing a company, an industry, a theme like "AI in healthcare" or "AI stocks",
or a product category is NOT enough. When unsure, answer 0.

Return JSON: {{"match": <storyline number, or 0 if none>}}"""

WRITE_PROMPT = """These news stories are all part of one storyline:

{stories}

Return JSON with exactly these keys:
- "kicker": the essence of the whole storyline in 2 to 7 words, like a friend texting you. Factual, no hype. Name the company or person; never a vague theme like "AI in healthcare".
- "headline": a neutral umbrella headline, at most 14 words, covering the storyline rather than any single article. Be specific.
- "why": ONE plain-English sentence explaining what is going on, including the cause or reason if the stories give it, and why it matters. Use only facts from the stories."""


def describe(story: sqlite3.Row) -> str:
    return f"{story['headline']} — {story['summary']}"


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def assign(conn: sqlite3.Connection, cutoff: str, budget: int) -> tuple[int, int]:
    stories = conn.execute(
        "SELECT * FROM stories WHERE umbrella_id IS NULL AND enriched_n > 0 AND scope != 'offtopic' "
        "AND last_seen >= ? ORDER BY first_seen", (cutoff,),
    ).fetchall()
    umbs = conn.execute("SELECT * FROM umbrellas WHERE last_seen >= ?", (cutoff,)).fetchall()
    u_ids = [u["id"] for u in umbs]
    u_text = {u["id"]: u["seed_text"] or u["headline"] for u in umbs}
    u_count = {u["id"]: u["n_stories"] for u in umbs}
    # The centroid stays the founding story's vector. If it averaged in every member, a storyline
    # would drift toward a broad theme and start swallowing unrelated stories.
    u_vec = [unit(from_blob(u["centroid"])) for u in umbs]

    calls = joined = 0
    for s in stories:
        v = unit(from_blob(s["centroid"]))
        match = 0
        if u_vec:
            sims = np.stack(u_vec) @ v
            top = [int(i) for i in np.argsort(-sims)[:3] if sims[i] >= config.UMBRELLA_CANDIDATE_SIM]
            if top and calls >= budget:
                continue  # out of model calls this run; decide next run (shown on its own until then)
            if top:
                options = "\n".join(f"{n}. {u_text[u_ids[i]]}" for n, i in enumerate(top, 1))
                try:
                    calls += 1
                    pick = clamp_int(ask_json(MATCH_PROMPT.format(story=describe(s), options=options))
                                     .get("match"), 0, len(top), 0)
                except Exception as e:
                    print(f"  ! match story {s['id']}: {type(e).__name__}: {e}")
                    pick = 0
                if pick:
                    match = top[pick - 1] + 1
        if match:
            k = match - 1
            uid, n = u_ids[k], u_count[u_ids[k]]
            u_count[uid] = n + 1
            conn.execute(
                "UPDATE umbrellas SET n_stories = ?, last_seen = MAX(last_seen, ?), "
                "first_seen = MIN(first_seen, ?) WHERE id = ?",
                (n + 1, s["last_seen"], s["first_seen"], uid),
            )
            joined += 1
        else:
            seed = describe(s)
            cur = conn.execute(
                "INSERT INTO umbrellas (centroid, first_seen, last_seen, n_stories, headline, seed_text) "
                "VALUES (?, ?, ?, 1, ?, ?)", (to_blob(v), s["first_seen"], s["last_seen"], s["headline"], seed),
            )
            uid = cur.lastrowid
            u_ids.append(uid)
            u_text[uid] = seed
            u_count[uid] = 1
            u_vec.append(v)
        conn.execute("UPDATE stories SET umbrella_id = ? WHERE id = ?", (uid, s["id"]))
        conn.commit()
    # Stories already in a storyline keep it fresh as they get new coverage.
    conn.execute("UPDATE umbrellas SET last_seen = (SELECT MAX(last_seen) FROM stories "
                 "WHERE umbrella_id = umbrellas.id)")
    conn.commit()
    return calls, joined


def write(conn: sqlite3.Connection, cutoff: str, budget: int) -> int:
    umbs = conn.execute(
        "SELECT id, n_stories FROM umbrellas WHERE last_seen >= ? AND n_stories >= 2 "
        "AND n_stories != written_n ORDER BY n_stories DESC LIMIT ?", (cutoff, budget),
    ).fetchall()
    done = 0
    for u in umbs:
        stories = conn.execute(
            "SELECT s.*, (SELECT COUNT(DISTINCT domain) FROM items WHERE story_id = s.id) AS outlets "
            "FROM stories s WHERE umbrella_id = ? ORDER BY outlets DESC LIMIT 8", (u["id"],),
        ).fetchall()
        text = "\n".join(f"- ({s['outlets']} outlets) {describe(s)}" for s in stories)
        try:
            out = ask_json(WRITE_PROMPT.format(stories=text))
        except Exception as e:
            print(f"  ! write storyline {u['id']}: {type(e).__name__}: {e}")
            continue
        conn.execute(
            "UPDATE umbrellas SET kicker = ?, headline = ?, why = ?, written_n = ? WHERE id = ?",
            (str(out.get("kicker") or stories[0]["kicker"])[:90],
             str(out.get("headline") or stories[0]["headline"])[:200],
             str(out.get("why") or stories[0]["summary"])[:500], u["n_stories"], u["id"]),
        )
        conn.commit()
        done += 1
    return done


def run(conn: sqlite3.Connection) -> None:
    cutoff = (now_utc() - timedelta(hours=config.WINDOW_HOURS)).isoformat()
    calls, joined = assign(conn, cutoff, config.UMBRELLA_LIMIT)
    written = write(conn, cutoff, config.UMBRELLA_LIMIT)
    print(f"umbrella: {calls} checks, {joined} stories joined a storyline, {written} storylines written")
