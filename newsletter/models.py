"""Model releases: which lab shipped which model, open weights or not, plus Hugging Face trending."""

import re
import sqlite3
from datetime import timedelta

import httpx

from . import config
from .ingest import now_utc
from .llm import ask_json, pick

PROMPT = """Here is a news story:

{story}

Is this story the launch or announcement of a specific new AI model (a new model or model version
from a lab, not an app feature, a product built on someone else's model, a chip, or a paper)?

Return JSON with exactly these keys:
- "is_model": true or false.
- "provider": the lab that made the model, e.g. "OpenAI", "Google", "DeepSeek", "Alibaba (Qwen)". Empty if not a model.
- "model": the model's exact name as reported, e.g. "GPT-6.2", "Qwen 4 72B". Empty if not a model.
- "open_weights": true if the weights are downloadable (open-weight/open-source), false if API or app only, null if the story doesn't say.
- "modality": one of text, multimodal, image, video, audio, code, robotics, other.
- "what": what is new about it in at most 12 words, using only facts from the story."""

OPEN_BY_DEFAULT = {"DeepSeek", "Alibaba (Qwen)", "Moonshot (Kimi)", "Zhipu (Z.ai)", "MiniMax", "Ai2"}


def looks_like_model(name: str) -> bool:
    """Real model names carry a version ("GPT-6.2", "Qwen 4", "GLM-5.4"); products and vague
    phrases ("Claude Ship", "specialized AI models") don't. The small model can't tell them apart."""
    name = name.strip()
    generic = re.search(r"\b(parameters?|models?|version|update|series)\b", name, re.I)
    return (bool(re.search(r"\d", name)) and not generic and not name[0].isdigit()
            and name.lower() not in config.PROVIDER_ALIASES and len(name) <= 40)


def family(name: str):
    """(provider, open_weights) from the model's family name, or (None, None) if unknown."""
    low = name.strip().lower()
    for prefix, provider, open_weights in config.MODEL_FAMILIES:
        if low.startswith(prefix):
            return provider, open_weights
    return None, None


def canonical(provider: str) -> str:
    p = (provider or "").strip()
    return config.PROVIDER_ALIASES.get(p.lower(), p)


def extract(conn: sqlite3.Connection) -> int:
    since = (now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)).isoformat()
    stories = conn.execute(
        """SELECT s.* FROM stories s LEFT JOIN releases r ON r.story_id = s.id
           WHERE s.kind = 'release' AND s.layer IN ('models', 'apps') AND s.last_seen >= ?
             AND (r.story_id IS NULL OR s.enriched_n > r.checked_n)
           ORDER BY s.importance DESC, s.last_seen DESC LIMIT ?""",
        (since, config.MODELS_LIMIT),
    ).fetchall()
    done = 0
    for s in stories:
        try:
            out = ask_json(PROMPT.format(story=f"{s['headline']} — {s['summary']}"))
        except Exception as e:
            print(f"  ! release {s['id']}: {type(e).__name__}: {e}")
            continue
        is_model = out.get("is_model") is True and looks_like_model(str(out.get("model") or ""))
        model = str(out.get("model") or "").strip()
        provider = canonical(str(out.get("provider") or ""))
        ow = out.get("open_weights")
        open_weights = 1 if ow is True else 0 if ow is False else (1 if provider in OPEN_BY_DEFAULT else 0)
        # A known family overrides the small model's guesses (it once credited GPT-6.2 to Alibaba).
        fam_provider, fam_open = family(model)
        if fam_provider:
            provider, open_weights = fam_provider, int(fam_open)
        conn.execute(
            "INSERT OR REPLACE INTO releases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (s["id"], int(is_model), provider or None, str(out.get("model") or "")[:80] or None,
             open_weights, pick(out.get("modality"), ("text", "multimodal", "image", "video", "audio",
                                                       "code", "robotics", "other"), "other"),
             str(out.get("what") or "")[:160], s["enriched_n"]),
        )
        conn.commit()
        done += 1
    return done


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
    n = extract(conn)
    try:
        t = trending(conn)
    except Exception as e:  # keep the last snapshot if Hugging Face is down
        print(f"  ! hf trending: {type(e).__name__}: {e}")
        t = 0
    print(f"models: {n} release stories checked, {t} trending models")
