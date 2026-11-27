"""Usage: python -m newsletter [run|ingest|cluster|triage|enrich|umbrella|models|grades|discover|render]"""

import sys

from . import cluster, db, discover, enrich, grades, ingest, models, render, triage, umbrella

STEPS = {
    "ingest": ingest.run,
    "cluster": cluster.run,
    "triage": triage.run,
    "enrich": enrich.run,
    "umbrella": umbrella.run,
    "models": models.run,
    "grades": grades.run,
    "discover": discover.run,
    "render": render.run,
}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd != "run" and cmd not in STEPS:
        sys.exit(__doc__)
    conn = db.connect()
    db.sync_sources(conn, ingest.now_utc().isoformat())
    for name, step in STEPS.items():
        if cmd in ("run", name):
            step(conn)


if __name__ == "__main__":
    main()
