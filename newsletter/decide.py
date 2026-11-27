"""Fixed-choice questions answered by a one-pass decision model (Decider, through llama.cpp).

All questions about a story are answered from a single read of it: the model is shown the
context and every question, and the probability of each option letter is read at each answer
slot. No text is generated, so it is fast and every answer is one of the options.
"""

from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _model():
    from decider.infer import Decider  # heavy import (torch, llama.cpp); only load when triage runs
    return Decider(config.DECIDER_REPO, gguf_file=config.DECIDER_FILE,
                   gguf_options={"n_ctx": 4096, "n_threads": config.DECIDER_THREADS})


def ask(context: str, questions: dict) -> dict:
    """questions: {name: (question, {key: option text})}. Returns {name: {key: probability}}."""
    names = list(questions)
    payload = [{"question": q, "options": list(opts.values())} for q, opts in questions.values()]
    results = _model().decide(context, payload)
    out = {}
    for name, res in zip(names, results):
        keys = list(questions[name][1])
        out[name] = {k: p for k, p in zip(keys, res["probs_list"])}
    return out
