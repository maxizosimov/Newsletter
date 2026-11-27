"""Write up the stories that passed triage: a short essence line, a headline and one sentence.

Labels (layer, kind, interest, ...) come from the triage step's decision model; this step only
writes text, and only for stories worth showing.
"""

import sqlite3
from datetime import timedelta

from . import config
from .ingest import now_utc
from .llm import ask_json

PROMPT = """You are the editor of a calm, no-hype AI briefing.
Below are reports from different outlets that all describe ONE story.

{reports}

Return JSON with exactly these keys:
- "kicker": the essence in 2 to 6 words, like a friend texting you the news. Factual, no hype. Name the company or person. Examples: "Huang is back at Nvidia", "Anthropic shares slide after IPO", "Google ships Gemini 3".
- "headline": neutral headline, at most 12 words.
- "summary": ONE plain-English sentence: what happened and, if the reports say so, why (the cause or reason). Use only facts stated in the reports; never invent numbers, names or details.
"""


def format_reports(items: list[sqlite3.Row]) -> str:
    # The longest snippets carry the most facts; keep the prompt small.
    chosen = sorted(items, key=lambda i: len(i["snippet"] or ""), reverse=True)[:8]
    lines = []
    for i in chosen:
        line = f"- [{i['publisher']}] {i['title']}"
        if i["snippet"]:
            line += f" — {i['snippet'][:300]}"
        lines.append(line)
    return "\n".join(lines)


def write(items: list[sqlite3.Row]) -> dict:
    out = ask_json(PROMPT.format(reports=format_reports(items)))
    return {
        "kicker": str(out.get("kicker") or "")[:80] or items[0]["title"][:80],
        "headline": str(out.get("headline") or items[0]["title"])[:200],
        "summary": str(out.get("summary") or "")[:500],
    }


def run(conn: sqlite3.Connection) -> None:
    news_cutoff = (now_utc() - timedelta(hours=config.WINDOW_HOURS)).isoformat()
    lab_cutoff = (now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)).isoformat()
    # Stories that passed triage and are new or grew by half since they were written; biggest first.
    stories = conn.execute(
        """SELECT s.id, s.n_items, COUNT(DISTINCT i.domain) AS outlets
           FROM stories s JOIN items i ON i.story_id = s.id
           WHERE s.triaged_n > 0 AND s.scope != 'offtopic'
             AND (s.enriched_n = 0 OR s.n_items >= s.enriched_n * 1.5 + 1)
             AND s.last_seen >= ?
           GROUP BY s.id
           HAVING s.interest >= ? OR outlets >= ?
           ORDER BY s.last_seen >= ? DESC, outlets DESC, s.interest DESC LIMIT ?""",
        (lab_cutoff, config.INTEREST_THRESHOLD, config.COVERAGE_OVERRIDE, news_cutoff, config.ENRICH_LIMIT),
    ).fetchall()
    done = 0
    for s in stories:
        items = conn.execute("SELECT * FROM items WHERE story_id = ?", (s["id"],)).fetchall()
        try:
            out = write(items)
        except Exception as e:
            print(f"  ! story {s['id']}: {type(e).__name__}: {e}")
            continue
        conn.execute("UPDATE stories SET kicker = ?, headline = ?, summary = ?, enriched_n = ? WHERE id = ?",
                     (out["kicker"], out["headline"], out["summary"], s["n_items"], s["id"]))
        conn.commit()
        done += 1
        if done % 20 == 0:
            print(f"  written {done}/{len(stories)}", flush=True)
    print(f"enrich: {done} stories written up")
