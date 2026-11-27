"""First pass over every story: is it worth an AI engineer's attention, and where does it belong?

A fast decision model reads each story once and answers every question from that one read.
Concrete yes/no questions filter out the noise (deals, stock tips, press releases); two signal
questions plus coverage decide what is worth writing up. Only stories that pass go on to the
slower writing model.
"""

import sqlite3
from datetime import timedelta

from . import config
from .decide import ask
from .enrich import format_reports
from .ingest import now_utc

YES_NO = {True: "yes", False: "no"}
QUESTIONS = {
    # Noise filters: small models answer concrete questions far better than "is this interesting?".
    "deal": ("Is this a shopping deal, discount, sale or price drop on a product?", YES_NO),
    "stocks": ("Is this mainly about stock prices, stock picks or investment advice?", YES_NO),
    "promo": ("Is this a promotional press release, award, event announcement or marketing piece?", YES_NO),
    # Signal.
    "signal": ("Does this report something concrete and new from a major AI lab, big tech company, chipmaker "
               "or government: a model, research result, product launch, large deal, executive change, lawsuit "
               "or policy?", YES_NO),
    "learn": ("Would a working AI engineer learn something new and useful about AI technology or the AI "
              "industry from this?", YES_NO),
    # Where it belongs.
    "scope": ("How does this story relate to AI?", {
        "core": "it is about AI itself",
        "adjacent": "it is about chips, power, tech companies or markets connected to AI",
        "offtopic": "it is not about AI"}),
    "layer": ("Where does this story sit in the AI stack?",
              {k: f"{v} ({config.LAYER_HINTS[k]})" for k, v in config.LAYERS.items()}),
    "kind": ("What kind of news is this?", {
        "release": "a model, product or feature launch", "research": "a research result or paper",
        "money": "funding, earnings, stocks or deals", "people": "executives or hiring",
        "policy": "government policy or regulation", "legal": "a lawsuit or court case",
        "incident": "an outage, attack, scandal or failure", "opinion": "opinion or analysis",
        "other": "something else"}),
    "lens": ("Which field is AI being applied to?", {**{l: l for l in config.LENSES}, None: "none of these"}),
    "status": ("How established is this news?", {
        "confirmed": "confirmed by an official source or several credible outlets",
        "claimed": "claimed by a company or person, not independently verified",
        "rumor": "rumor: anonymous sources or speculation"}),
}


def top(probs: dict):
    return max(probs, key=probs.get)


def interest_of(a: dict) -> float:
    """1-5: noise is 1; otherwise the two signal answers, averaged, stretched over 1..5."""
    if max(a["deal"][True], a["stocks"][True], a["promo"][True]) >= 0.5:
        return 1.0
    return 1 + 4 * (a["signal"][True] + a["learn"][True]) / 2


def passes(interest: float, scope: str, outlets: int) -> bool:
    if scope == "offtopic" or interest <= 1.0:
        return False
    return interest >= config.INTEREST_THRESHOLD or outlets >= config.COVERAGE_OVERRIDE


def run(conn: sqlite3.Connection) -> None:
    news_cutoff = (now_utc() - timedelta(hours=config.WINDOW_HOURS)).isoformat()
    lab_cutoff = (now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)).isoformat()
    # New stories, or ones that grew by half since they were triaged; fresh news first.
    stories = conn.execute(
        """SELECT s.id, s.n_items FROM stories s
           WHERE (s.triaged_n = 0 OR s.n_items >= s.triaged_n * 1.5 + 1)
             AND (s.last_seen >= ? OR (s.last_seen >= ? AND EXISTS (
                  SELECT 1 FROM items li JOIN sources so ON so.id = li.source_id
                  WHERE li.story_id = s.id AND so.kind = 'primary')))
           ORDER BY s.last_seen >= ? DESC, s.n_items DESC LIMIT ?""",
        (news_cutoff, lab_cutoff, news_cutoff, config.TRIAGE_LIMIT),
    ).fetchall()
    kept = 0
    for i, s in enumerate(stories, 1):
        items = conn.execute("SELECT * FROM items WHERE story_id = ? ORDER BY length(snippet) DESC",
                             (s["id"],)).fetchall()
        try:
            a = ask(format_reports(items[:5]), QUESTIONS)
        except Exception as e:
            print(f"  ! triage story {s['id']}: {type(e).__name__}: {e}")
            continue
        interest = interest_of(a)
        scope = top(a["scope"])
        if passes(interest, scope, len({it["domain"] for it in items})):
            kept += 1
        conn.execute(
            "UPDATE stories SET interest = ?, importance = ?, scope = ?, layer = ?, kind = ?, lens = ?, status = ?, "
            "triaged_n = ? WHERE id = ?",
            (interest, max(1, min(5, round(interest))), scope, top(a["layer"]), top(a["kind"]),
             top(a["lens"]), top(a["status"]), s["n_items"], s["id"]),
        )
        if i % 100 == 0:
            conn.commit()
            print(f"  triaged {i}/{len(stories)}", flush=True)
    conn.commit()
    print(f"triage: {len(stories)} stories read, {kept} worth writing up")
