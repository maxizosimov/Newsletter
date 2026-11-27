# Newsletter

A calm, local-first AI briefing. It reads AI news from dozens of sources, groups coverage of the same event into stories, ties related stories into storylines, and lays them out on a map of the AI stack, from power and chips up to policy, so you can see at a glance what is happening and how big it is.

All summarizing is done by an open model running through [Ollama](https://ollama.com): on your machine, or on the GitHub runner in the scheduled workflow. No API keys.

## Pipeline

| Step | What it does |
| --- | --- |
| `ingest` | Fetches every source (RSS/Atom, Google News searches, Hacker News, Hugging Face daily papers). Aggregated items are credited to the real outlet, and each item's outbound links are recorded. |
| `cluster` | Embeds headlines locally and groups items about the same event into a story (average-linkage, so vague "AI" headlines don't snowball). |
| `triage` | A one-pass decision model ([Decider](https://github.com/Mapika/decider) 4B, via llama.cpp) reads every story once and answers all its questions from that single read (about a second per story on an M2): noise filters (deal? stock tip? press release?), signal (concrete news from a major player? would an AI engineer learn something?), and where it belongs (layer, kind, field, core AI vs adjacent, confirmed/claimed/rumor). Only stories that pass, or that are widely covered, go further. |
| `enrich` | The writing model writes up the stories that passed triage: a 2–6 word essence, a headline and one sentence with the cause. |
| `models` | Pulls the lab, model name and open-weights flag out of launch stories, and snapshots Hugging Face trending (minus quantized re-uploads) for the Models page. |
| `umbrella` | Ties related stories into storylines (embeddings propose, the model confirms it's the same saga) and writes one umbrella explanation per storyline. |
| `grades` | Grades every outlet on two axes from its last 30 days: **fast** (often first on stories others pick up) and **deep** (source type, plus how many other outlets cite it). Runs probation for discovered sources. |
| `discover` | Sites that several sources keep citing become candidates: their feed is found automatically, the model checks they're about AI, and they start on probation. |
| `render` | Writes `output/index.html` with two tabs. **News**: a front page (lead and three seconds), a bubble map of storylines grouped by layer, and the wire. **Models**: a 30-day release timeline, frontier labs and open-weight models side by side, and Hugging Face trending. Every storyline opens a panel with best read, who broke it, momentum, angles and all coverage. |

## Run locally

```sh
ollama pull nomic-embed-text
ollama pull qwen2.5:7b
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m newsletter          # all steps, or one: ingest | cluster | triage | enrich | umbrella | models | grades | discover | render
open output/index.html
```

Settings (models, windows, thresholds, stack layers, source priors) live in `newsletter/config.py`; seed sources in `newsletter/sources.json`.

## Schedule

`.github/workflows/brief.yml` runs at 7, 8 and 9 AM, 5 PM and 10 PM New York time. Each run restores the database from the `data` branch, runs the pipeline with Ollama on the runner, saves the database back (always a single commit), and publishes the page to GitHub Pages.
