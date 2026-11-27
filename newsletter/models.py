"""Model releases, tracked lab by lab, plus Hugging Face trending.

Launches are found without a language model: for every tracked lab the news is searched for
launch headlines, and a headline counts when it names one of the lab's model families with a
version ("Claude Fable 5.2", "GPT-6.2 Astra", "GLM-5.4") next to a launch verb. Rumours,
previews and comparisons ("rivals Opus 5.5") don't count. Every launch found is kept for good,
so each lab always shows its latest model.
"""

import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timedelta

import feedparser
import httpx

from . import config
from .db import domain_of
from .ingest import clean, entry_time, now_utc

LAUNCH_RE = re.compile(
    r"\b(launch(?:es|ed|ing)?|releas(?:es|ed|ing)|unveil(?:s|ed|ing)?|debut(?:s|ed)?|introduc(?:es|ed|ing)|"
    r"announc(?:es|ed|ing)|rolls? out|rolled out|ships|shipped|now available|is here|arrives?|drops|"
    r"open[- ]sources?d?|goes live|is live)\b", re.I)
RUMOUR_RE = re.compile(
    r"\b(prepar\w*|testing|tests|test|reportedly|rumou?r\w*|leak\w*|release date|when will|could|might|may|"
    r"expected|expect|plans?|planning|teases?|teased|soon|upcoming|coming|next|delay\w*|pulls?|"
    r"degraded|outage|issue|bug|nears?|nearing|set to|will|to launch|to release|ahead of launch)\b", re.I)
# Everything after one of these is about some other model being compared against.
COMPARE_RE = re.compile(r"\b(rivals?|beats?|beating|vs\.?|versus|than|outperforms?|takes on|challenges?|"
                        r"compared|against|match\w*|like|cost|costs|replac\w*|instead)\b", re.I)
# A version followed by one of these is a product or a whole family, not a model.
NOT_A_MODEL_RE = re.compile(r"^[\s-]*(?:[\w.-]+\s+){0,5}?(glasses|phones?|app|apps|device|headset|robots?|cars?|"
                            r"chips?|laptop|watch|earbuds|family|lineup|series)\b", re.I)
# "third Claude 5.5 model" counts members of a family, it doesn't name one.
ORDINAL_RE = re.compile(r"\b(second|third|fourth|fifth|another)\s+$", re.I)
VERSION = r"[- ]?([A-Za-z]?\d+(?:\.\d+)*[a-z]?)"
VARIANT = r"(?:[- ](" + "|".join(re.escape(v) for v in config.MODEL_VARIANTS) + r"))?"


def _compile():
    out = []
    for lab in config.LABS:
        for fam, open_weights, prefix in lab["families"]:
            # Family names in any case ("Gpt", "GLM"); variants only when capitalised ("Pro", not "small").
            rx = re.compile(r"(?<![\w-])((?i:" + fam + r"))" + VERSION + VARIANT + r"(?![\w.])")
            out.append((lab, rx, open_weights, prefix))
    return out


PATTERNS = _compile()


def model_key(name: str) -> str:
    return re.sub(r"[\s-]+", " ", name.lower().replace("claude ", "")).strip()


def tidy(fam: str, version: str, variant: str | None, prefix: str) -> str:
    fam = re.sub(r"\s+", " ", fam).strip()
    if prefix and not fam.lower().startswith(prefix.strip().lower()):
        fam = prefix + fam
    # Families written with a hyphen keep it ("GPT-6.2", "GLM-5.4"); the rest take a space.
    joiner = "-" if fam.upper() in {"GPT", "GLM", "GPT-OSS", "PHI", "MAI"} else " "
    name = f"{fam}{joiner}{version}"
    return f"{name} {variant}" if variant else name


def models_in(title: str) -> list[tuple[dict, str, bool]]:
    """(lab, model name, open weights) for every launch a headline announces."""
    if not LAUNCH_RE.search(title) or RUMOUR_RE.search(title):
        return []
    cut = COMPARE_RE.search(title)
    head = title[: cut.start()] if cut else title
    # Whoever comes before the launch verb is doing the launching: "Sakana AI releases X built on
    # Nemotron" is Sakana's launch, not NVIDIA's.
    verb = LAUNCH_RE.search(head)
    subject = head[: verb.start()] if verb else ""
    found, seen = [], set()
    for lab, rx, open_weights, prefix in PATTERNS:
        for m in rx.finditer(head):
            fam, version, variant = m.group(1), m.group(2), m.group(3)
            if not re.search(r"\d", version) or (version.isdigit() and int(version) > 50):
                continue  # "GPT 2026", "Grok 300" are years and counts, not versions
            if NOT_A_MODEL_RE.match(head[m.end():]) or ORDINAL_RE.search(head[: m.start()]):
                continue
            launcher_ok = (not subject.strip() or m.start() < len(subject)
                           or any(re.search(rf"\b{re.escape(w)}\b", subject, re.I) for w in lab["who"]))
            if not launcher_ok:
                continue
            if variant and variant in lab.get("closed_variants", []):
                open_weights = False
            name = tidy(fam, version, variant, prefix)
            key = (lab["name"], model_key(name))
            # The longer family wins ("GPT-oss-2" over "GPT"): skip a match inside one already found.
            if key in seen or any(m.start() >= s and m.end() <= e for s, e in [x[3] for x in found]):
                continue
            seen.add(key)
            found.append((lab, name, open_weights, (m.start(), m.end())))
    return [(lab, name, ow) for lab, name, ow, _ in found]


SLICE_DAYS = 15


def search(client: httpx.Client, lab: dict, window: str) -> list[dict]:
    verbs = "launches OR releases OR unveils OR debuts OR introduces OR announces OR \"rolls out\""
    q = f"({lab['search']}) ({verbs}) {window}"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    r = client.get(url)
    r.raise_for_status()
    out = []
    for e in feedparser.parse(r.content).entries:
        src = e.get("source") or {}
        publisher = src.get("title") or ""
        title = clean(e.get("title", ""), 300)
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        out.append({"url": e.get("link"), "title": title, "publisher": publisher,
                    "domain": domain_of(src.get("href", "")), "published": entry_time(e) or now_utc()})
    return out


def save(conn: sqlite3.Connection, item: dict) -> int:
    n = 0
    for lab, name, open_weights in models_in(item["title"]):
        cur = conn.execute(
            "INSERT OR IGNORE INTO launches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["url"], lab["name"], name, model_key(name), int(open_weights), item["title"],
             item["publisher"], item["domain"], item["published"].isoformat()))
        n += cur.rowcount
    return n


def track(conn: sqlite3.Connection) -> int:
    added = 0
    first = not conn.execute("SELECT 1 FROM launches LIMIT 1").fetchone()
    # Headlines already fetched by the news feeds (labs' own blogs among them) count too.
    for row in conn.execute("SELECT url, title, publisher, domain, published FROM items").fetchall():
        added += save(conn, {**dict(row), "published": datetime.fromisoformat(row["published"])})
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": config.USER_AGENT}) as client:
        # A search returns at most 100 headlines, and a lab's launch can drown in its other news.
        # So every run searches the last week, plus one 15-day slice of the older window, a different
        # slice each run, so a day's runs cover it all. The very first run sweeps every slice.
        now = now_utc()
        n_slices = config.LAUNCH_SEARCH_DAYS // SLICE_DAYS
        picked = range(n_slices) if first else [now.hour % n_slices]
        windows = ["when:7d"] + [
            f"after:{(now - timedelta(days=(k + 1) * SLICE_DAYS)).date()} before:{(now - timedelta(days=k * SLICE_DAYS - 1)).date()}"
            for k in picked]
        searches = [(lab, w) for lab in config.LABS for w in windows]
        for i, (lab, window) in enumerate(searches):
            if i:
                time.sleep(3)  # one host, so one polite request at a time
            try:
                try:
                    items = search(client, lab, window)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 429:
                        raise
                    time.sleep(30)  # asked to slow down: wait once, then try again
                    items = search(client, lab, window)
            except Exception as e:  # one failed search must not stop the others
                print(f"  ! launches {lab['name']}: {type(e).__name__}: {e}")
                continue
            for it in items:
                if it["url"]:
                    added += save(conn, it)
    conn.commit()
    return added


def is_copy(model_id: str) -> bool:
    org = model_id.split("/")[0].lower()
    low = model_id.lower()
    return org in config.HF_REUPLOADERS or any(m in low for m in config.HF_COPY_MARKERS)


def trending(conn: sqlite3.Connection) -> int:
    r = httpx.get("https://huggingface.co/api/models",
                  params={"sort": "trendingScore", "direction": -1, "limit": 100},
                  headers={"User-Agent": config.USER_AGENT}, timeout=30)
    r.raise_for_status()
    rows = [m for m in r.json() if "/" in m["id"] and not is_copy(m["id"])][: config.HF_TRENDING_LIMIT]
    now = now_utc().isoformat()
    conn.execute("DELETE FROM hf_trending")
    for rank, m in enumerate(rows, 1):
        conn.execute(
            "INSERT INTO hf_trending VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rank, m["id"], m["id"].split("/")[0], m.get("likes"), m.get("downloads"),
             m.get("trendingScore"), m.get("pipeline_tag"), m.get("createdAt"), now),
        )
    conn.commit()
    return len(rows)


def run(conn: sqlite3.Connection) -> None:
    n = track(conn)
    try:
        t = trending(conn)
    except Exception as e:  # keep the last snapshot if Hugging Face is down
        print(f"  ! hf trending: {type(e).__name__}: {e}")
        t = 0
    print(f"models: {n} new launch headlines, {t} trending models")
