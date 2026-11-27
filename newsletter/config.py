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
MODELS_WINDOW_DAYS = 30
MODELS_LIMIT = int(os.environ.get("MODELS_LIMIT", 80))
HF_TRENDING_LIMIT = 20
# Frontier labs always get a lane on the Models page, even in a quiet month.
FRONTIER_LABS = ["OpenAI", "Anthropic", "Google", "xAI", "Meta", "Mistral"]
# Spellings the model or news use -> one canonical lab name.
PROVIDER_ALIASES = {
    "openai": "OpenAI", "chatgpt": "OpenAI", "anthropic": "Anthropic", "claude": "Anthropic",
    "google": "Google", "google deepmind": "Google", "deepmind": "Google", "gemini": "Google",
    "xai": "xAI", "x.ai": "xAI", "grok": "xAI", "spacex": "xAI", "meta": "Meta", "meta ai": "Meta",
    "facebook": "Meta", "llama": "Meta", "mistral": "Mistral", "mistral ai": "Mistral",
    "deepseek": "DeepSeek", "alibaba": "Alibaba (Qwen)", "qwen": "Alibaba (Qwen)",
    "moonshot": "Moonshot (Kimi)", "moonshot ai": "Moonshot (Kimi)", "kimi": "Moonshot (Kimi)",
    "zhipu": "Zhipu (Z.ai)", "z.ai": "Zhipu (Z.ai)", "glm": "Zhipu (Z.ai)", "minimax": "MiniMax",
    "nvidia": "NVIDIA", "microsoft": "Microsoft", "amazon": "Amazon", "aws": "Amazon",
    "apple": "Apple", "cohere": "Cohere", "ai2": "Ai2", "allen institute for ai": "Ai2",
    "tencent": "Tencent", "baidu": "Baidu", "bytedance": "ByteDance", "xiaomi": "Xiaomi",
    "ibm": "IBM", "thinking machines": "Thinking Machines", "reflection ai": "Reflection AI",
    "gdm": "Google", "sber": "Sber", "sberbank": "Sber",
}
# Model families say who made a model and whether its weights are open, more reliably than a
# small model reading the article. Checked in order against the start of the model name.
MODEL_FAMILIES = [
    ("gpt-oss", "OpenAI", True), ("gpt", "OpenAI", False), ("o3", "OpenAI", False), ("o4", "OpenAI", False),
    ("sora", "OpenAI", False), ("claude", "Anthropic", False), ("gemma", "Google", True),
    ("gemini", "Google", False), ("genie", "Google", False), ("veo", "Google", False), ("imagen", "Google", False),
    ("grok", "xAI", False), ("llama", "Meta", True), ("mistral large", "Mistral", False),
    ("mistral medium", "Mistral", False), ("mistral", "Mistral", True), ("magistral", "Mistral", True),
    ("devstral", "Mistral", True), ("codestral", "Mistral", False), ("qwen", "Alibaba (Qwen)", True),
    ("wan", "Alibaba (Qwen)", True), ("deepseek", "DeepSeek", True), ("glm", "Zhipu (Z.ai)", True),
    ("kimi", "Moonshot (Kimi)", True), ("minimax", "MiniMax", True), ("nemotron", "NVIDIA", True),
    ("cosmos", "NVIDIA", True), ("phi", "Microsoft", True), ("nova", "Amazon", False),
    ("gigachat", "Sber", False), ("hunyuan", "Tencent", True), ("ernie", "Baidu", True),
    ("doubao", "ByteDance", False), ("seed", "ByteDance", True), ("olmo", "Ai2", True),
    ("command", "Cohere", False), ("granite", "IBM", True),
]
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
