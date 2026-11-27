import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "newsletter.db"
OUTPUT_DIR = ROOT / "output"
SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:7b")
# A one-pass decision model: answers fixed-choice questions from letter probabilities, no text.
DECIDER_REPO = os.environ.get("DECIDER_REPO", "Mapika/decider-4b-GGUF")
DECIDER_FILE = os.environ.get("DECIDER_FILE", "decider-4b-v3-Q4_K_M.gguf")
DECIDER_THREADS = int(os.environ.get("DECIDER_THREADS", os.cpu_count() or 4))

USER_AGENT = "Mozilla/5.0 (compatible; personal-ai-digest/0.1)"

# Only items published within this window are grouped into stories and shown.
WINDOW_HOURS = 72
# Items are kept this long so source grades have history to learn from.
RETENTION_DAYS = 30
# An item joins a story when its average similarity to the story's items is at least this.
CLUSTER_THRESHOLD = 0.84
# Stories at least this similar to a storyline are offered to the model as possible members.
UMBRELLA_CANDIDATE_SIM = 0.74
# Hugging Face daily papers: keep only the most upvoted.
HF_PAPERS_LIMIT = 25
# Triage: a story is written up and shown only if an AI engineer would find it interesting
# (expected score on a 1-5 scale) or enough outlets cover it that it matters regardless.
INTEREST_THRESHOLD = 3.6
COVERAGE_OVERRIDE = 6
TRIAGE_LIMIT = int(os.environ.get("TRIAGE_LIMIT", 1500))
# Caps on model calls per run, most important work first.
ENRICH_LIMIT = int(os.environ.get("ENRICH_LIMIT", 150))
UMBRELLA_LIMIT = int(os.environ.get("UMBRELLA_LIMIT", 120))
# Discovery: how many unknown sites to inspect per run, and how often one must be cited first.
DISCOVERY_PER_RUN = 15
DISCOVERY_MIN_MENTIONS = 3
DISCOVERY_MIN_CITERS = 2
# Probation: a discovered source needs this many on-topic items to be promoted, or is muted after.
PROMOTE_MIN_ITEMS = 3
PROBATION_DAYS = 10

# Where a story sits in the AI stack, top to bottom.
LAYERS = {
    "society": "Policy & society",
    "business": "Money & distribution",
    "apps": "Applications",
    "models": "Models",
    "infra": "Cloud & datacenters",
    "chips": "Chips & hardware",
    "energy": "Power & energy",
}
LAYER_HINTS = {
    "society": "regulation, lawsuits, safety, jobs, culture",
    "business": "funding, IPOs, stocks, deals, executives, go-to-market",
    "apps": "products, agents and tools built on AI, adoption",
    "models": "model releases, training, benchmarks, model research",
    "infra": "datacenters, cloud, compute deals, networking",
    "chips": "GPUs, accelerators, fabs, semiconductors",
    "energy": "electricity, grid, nuclear and power for AI",
}
# The field AI is being applied to, when there is one.
LENSES = ["medicine", "science", "math", "robotics", "defense", "finance", "education",
          "creative", "security", "climate", "legal"]
KINDS = ["release", "research", "money", "people", "policy", "legal", "incident", "opinion", "other"]

# Prior trust in a source kind before its own track record builds up.
KIND_DEPTH = {"primary": 0.9, "papers": 0.85, "analysis": 0.8, "news": 0.6, "aggregator": 0.5}

# Outlets that arrive through aggregators (Google News, HN), keyed by domain.
OUTLET_PRIOR = {
    "reuters.com": 0.9, "bloomberg.com": 0.9, "ft.com": 0.9, "wsj.com": 0.9, "theinformation.com": 0.9,
    "nytimes.com": 0.85, "apnews.com": 0.85, "economist.com": 0.85, "nature.com": 0.9,
    "science.org": 0.9, "washingtonpost.com": 0.8, "bbc.com": 0.8, "bbc.co.uk": 0.8,
    "technologyreview.com": 0.8, "semafor.com": 0.75, "theguardian.com": 0.75, "axios.com": 0.7,
    "cnbc.com": 0.7, "wired.com": 0.7, "arstechnica.com": 0.7, "theverge.com": 0.65,
    "techcrunch.com": 0.65, "fortune.com": 0.65, "businessinsider.com": 0.55, "forbes.com": 0.5,
    "finance.yahoo.com": 0.4, "uk.finance.yahoo.com": 0.4, "fool.com": 0.3, "benzinga.com": 0.3,
}
DEFAULT_OUTLET_PRIOR = 0.5

# Sites that are never sources in their own right: social networks, link shorteners, hosts.
DISCOVERY_BLOCKLIST = {
    "twitter.com", "x.com", "t.co", "youtube.com", "youtu.be", "linkedin.com", "facebook.com",
    "instagram.com", "threads.net", "bsky.app", "tiktok.com", "reddit.com", "old.reddit.com",
    "github.com", "gist.github.com", "google.com", "news.google.com", "docs.google.com",
    "drive.google.com", "wikipedia.org", "en.wikipedia.org", "apple.com", "apps.apple.com",
    "podcasts.apple.com", "spotify.com", "open.spotify.com", "amazon.com", "substack.com",
    "medium.com", "arxiv.org", "doi.org", "huggingface.co", "discord.com", "discord.gg",
    "archive.org", "web.archive.org", "archive.ph", "bit.ly", "goo.gl", "tinyurl.com",
    "patreon.com", "buymeacoffee.com", "paypal.com", "eepurl.com", "mailchi.mp",
    "news.ycombinator.com", "hnrss.org", "feedburner.com", "feeds.feedburner.com", "gravatar.com",
    "wp.me", "wordpress.com", "creativecommons.org", "w3.org", "schema.org", "openreview.net",
}

# ---- Models page ----
# Labs' own posts are kept (and grouped into stories) this long, longer than ordinary news.
MODELS_WINDOW_DAYS = 30
# Launch news is searched this far back for every tracked lab; found releases are kept for good,
# so each lab always shows its latest model even after a quiet stretch.
LAUNCH_SEARCH_DAYS = 60
HF_TRENDING_LIMIT = 20
# Labs whose releases are tracked: the news search for each, who may announce its launches (the lab,
# its brands, its leaders), its own sites (preferred as the link), and its model families. A family is a name pattern; the version and an optional variant follow it.
# (family regex, open weights, display prefix)
LABS = [
    {"name": "OpenAI", "who": ["OpenAI", "ChatGPT", "Altman"], "search": "OpenAI", "sites": ["openai.com"],
     "families": [(r"GPT-oss", True, ""), (r"GPT", False, ""), (r"Sora", False, "")]},
    {"name": "Anthropic", "who": ["Anthropic", "Claude", "Amodei"], "search": "Anthropic OR Claude", "sites": ["anthropic.com", "claude.com"],
     "families": [(r"(?:Claude\s+)?(?:Fable|Mythos|Opus|Sonnet|Haiku)", False, "Claude "), (r"Claude", False, "")]},
    {"name": "Google", "who": ["Google", "DeepMind", "Gemini", "Pichai", "Hassabis"], "search": "Gemini OR DeepMind OR Gemma", "sites": ["blog.google", "deepmind.google", "googleblog.com"],
     "families": [(r"Gemma", True, ""), (r"Gemini", False, ""), (r"Veo", False, ""), (r"Imagen", False, ""), (r"Genie", False, "")]},
    {"name": "xAI", "who": ["xAI", "Grok", "Musk", "SpaceX"], "search": "xAI OR Grok", "sites": ["x.ai"], "families": [(r"Grok\s+Voice", False, ""), (r"Grok", False, "")]},
    {"name": "Meta", "who": ["Meta", "Zuckerberg", "Llama"], "search": "Meta Llama OR \"Meta AI\"", "sites": ["ai.meta.com", "about.fb.com"],
     "families": [(r"Llama", True, "")]},
    {"name": "Mistral", "who": ["Mistral"], "search": "\"Mistral AI\" OR Mistral", "sites": ["mistral.ai"],
     "families": [(r"Mistral\s+(?:Large|Medium)", False, ""), (r"Mistral(?:\s+Small)?", True, ""),
                  (r"Magistral", True, ""), (r"Devstral", True, ""), (r"Codestral", False, "")]},
    {"name": "DeepSeek", "who": ["DeepSeek"], "search": "DeepSeek", "sites": ["deepseek.com"], "families": [(r"DeepSeek", True, "")]},
    {"name": "Alibaba (Qwen)", "who": ["Alibaba", "Qwen"], "closed_variants": ["Max"], "search": "Qwen OR \"Alibaba AI\"", "sites": ["qwenlm.github.io", "alibabacloud.com"],
     "families": [(r"Qwen", True, ""), (r"Wan", True, "")]},
    {"name": "Moonshot (Kimi)", "who": ["Moonshot", "Kimi"], "search": "Kimi OR \"Moonshot AI\"", "sites": ["moonshot.ai", "moonshot.cn"],
     "families": [(r"Kimi", True, "")]},
    {"name": "Zhipu (Z.ai)", "who": ["Zhipu", "Z.ai", "GLM"], "search": "Zhipu OR GLM OR \"Z.ai\"", "sites": ["z.ai", "zhipuai.cn"],
     "families": [(r"GLM", True, "")]},
    {"name": "MiniMax", "who": ["MiniMax"], "search": "MiniMax", "sites": ["minimax.io", "minimaxi.com"], "families": [(r"MiniMax", True, "")]},
    {"name": "NVIDIA", "who": ["Nvidia", "Huang", "Nemotron"], "search": "Nvidia Nemotron OR Cosmos", "sites": ["nvidia.com"],
     "families": [(r"Nemotron", True, ""), (r"Cosmos", True, "")]},
    {"name": "Microsoft", "who": ["Microsoft", "Nadella", "Suleyman"], "search": "Microsoft Phi OR \"Microsoft AI\" model", "sites": ["microsoft.com"],
     "families": [(r"Phi", True, ""), (r"MAI", False, "")]},
]
# Words that may follow a version as part of a model's name ("Gemini 4 Pro", "GPT-6.2 Astra").
MODEL_VARIANTS = ["Pro", "Flash-Lite", "Flash", "Mini", "Nano", "Ultra", "Max", "Lite", "Turbo", "Air",
                  "Thinking", "Instant", "Plus", "Codex", "Coder", "Omni", "Vision", "Fast", "Heavy",
                  "Preview", "Exp", "Super", "Maverick", "Scout", "Behemoth", "Neon", "Carbon", "Astra",
                  "Sol", "Cyber", "Large", "Medium", "Small", "Reasoner", "Agent"]
# Where a lab or Hugging Face org is based, for the open-weights pane.
COUNTRY = {
    "OpenAI": "US", "Anthropic": "US", "Google": "US", "xAI": "US", "Meta": "US", "Mistral": "FR",
    "DeepSeek": "CN", "Alibaba (Qwen)": "CN", "Moonshot (Kimi)": "CN", "Zhipu (Z.ai)": "CN",
    "MiniMax": "CN", "NVIDIA": "US", "Microsoft": "US", "Amazon": "US", "Apple": "US",
    "Cohere": "CA", "Ai2": "US", "Tencent": "CN", "Baidu": "CN", "ByteDance": "CN", "Xiaomi": "CN",
    "IBM": "US", "Thinking Machines": "US", "Reflection AI": "US", "Sber": "RU",
    # Hugging Face orgs
    "qwen": "CN", "deepseek-ai": "CN", "moonshotai": "CN", "zai-org": "CN", "thudm": "CN",
    "minimaxai": "CN", "tencent": "CN", "tencent-hunyuan": "CN", "baidu": "CN", "paddlepaddle": "CN",
    "bytedance-seed": "CN", "bytedance": "CN", "xiaomimimo": "CN", "stepfun-ai": "CN",
    "internlm": "CN", "opengvlab": "CN", "inclusionai": "CN", "meituan-longcat": "CN",
    "kwaipilot": "CN", "kwai-kolors": "CN", "baai": "CN", "openbmb": "CN", "wan-ai": "CN",
    "alibaba-nlp": "CN", "skywork": "CN", "meta-llama": "US", "facebook": "US", "google": "US",
    "nvidia": "US", "microsoft": "US", "openai": "US", "allenai": "US", "ibm-granite": "US",
    "apple": "US", "amazon": "US", "thinkingmachines": "US", "liquidai": "US", "salesforce": "US",
    "mistralai": "FR", "black-forest-labs": "DE", "stabilityai": "GB", "lightricks": "IL",
    "ai21labs": "IL", "tiiuae": "AE", "sakanaai": "JP", "cohereforai": "CA", "coherelabs": "CA",
    "huggingfacetb": "US",
}
# Re-uploaders and quantizers: their repos are copies of someone else's model.
HF_REUPLOADERS = {"unsloth", "bartowski", "lmstudio-community", "mlx-community", "thebloke",
                  "quantfactory", "mradermacher", "atomicchat", "nousresearch-quants", "ggml-org"}
HF_COPY_MARKERS = ("gguf", "-awq", "-gptq", "-mlx", "-4bit", "-8bit", "-fp8", "-int4", "-int8",
                   "uncensored", "abliterated", "-exl2", "-bnb")
