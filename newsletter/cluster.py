"""Group items that describe the same event into stories, using local embeddings."""

import sqlite3
from datetime import timedelta

import httpx
import numpy as np

from . import config
from .db import from_blob, to_blob
from .ingest import now_utc


def embed(texts: list[str]) -> np.ndarray:
    vectors = []
    with httpx.Client(timeout=300) as client:
        for i in range(0, len(texts), 64):
            batch = [f"clustering: {t}" for t in texts[i : i + 64]]
            r = client.post(f"{config.OLLAMA_URL}/api/embed",
                            json={"model": config.EMBED_MODEL, "input": batch})
            r.raise_for_status()
            vectors.extend(r.json()["embeddings"])
    m = np.asarray(vectors, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def item_text(row: sqlite3.Row) -> str:
    return f"{row['title']}. {row['snippet'] or ''}"[:500]


def run(conn: sqlite3.Connection) -> None:
    # Only lab announcements are kept beyond the news window, so this is cheap.
    cutoff = (now_utc() - timedelta(days=config.MODELS_WINDOW_DAYS)).isoformat()
    items = conn.execute(
        "SELECT * FROM items WHERE story_id IS NULL AND published >= ? ORDER BY published",
        (cutoff,),
    ).fetchall()
    if not items:
        print("cluster: nothing new")
        return

    vecs = embed([item_text(r) for r in items])

    stories = conn.execute(
        "SELECT id, centroid, n_items FROM stories WHERE last_seen >= ?", (cutoff,)
    ).fetchall()
    ids = [s["id"] for s in stories]
    counts = [s["n_items"] for s in stories]
    centroids = [from_blob(s["centroid"]).copy() for s in stories]

    created = 0
    for row, v in zip(items, vecs):
        best = -1
        if centroids:
            sims = np.stack(centroids) @ v
            best = int(sims.argmax())
            if sims[best] < config.CLUSTER_THRESHOLD:
                best = -1
        if best >= 0:
            n = counts[best]
            # Keep the centroid as the plain mean of unit vectors, so centroid @ v is the
            # item's average similarity to every member (average linkage). That stops loose
            # "AI in general" headlines from snowballing into one giant story.
            centroids[best] = (centroids[best] * n + v) / (n + 1)
            counts[best] = n + 1
            sid = ids[best]
            conn.execute(
                "UPDATE stories SET centroid = ?, n_items = ?, "
                "last_seen = MAX(last_seen, ?), first_seen = MIN(first_seen, ?) WHERE id = ?",
                (to_blob(centroids[best]), n + 1, row["published"], row["published"], sid),
            )
        else:
            cur = conn.execute(
                "INSERT INTO stories (centroid, first_seen, last_seen, n_items) VALUES (?, ?, ?, 1)",
                (to_blob(v), row["published"], row["published"]),
            )
            sid = cur.lastrowid
            ids.append(sid)
            counts.append(1)
            centroids.append(v.copy())
            created += 1
        conn.execute("UPDATE items SET story_id = ?, embedding = ? WHERE id = ?",
                     (sid, to_blob(v), row["id"]))
    conn.commit()
    print(f"cluster: {len(items)} items, {created} new stories")
