"""Fast multi-model deliberation for Corvi."""
from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen


def _ask(base_url, api_key, model, prompt, timeout=300):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            # HDD-backed council models must not all remain resident. Ollama
            # will unload this runner after the response, allowing the next
            # model to load instead of failing under the 16 GB memory limit.
            "stream": False, "keep_alive": 0, "options": {"num_ctx": 1536}}
    last_error = None
    for attempt in range(2):
        try:
            req = Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
            with urlopen(req, timeout=timeout) as response:
                data = json.load(response)
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
            if content:
                return content
            raise RuntimeError("Ollama returned an empty response")
        except Exception as exc:  # transient runner/EOF errors are common on HDDs
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
    raise last_error


def deliberate(base_url, api_key, models, prompt, research="", on_progress=None):
    """Ask multiple models concurrently, then synthesize their strongest points."""
    task = prompt + ("\n\nResearch context:\n" + research if research else "")
    answers = {}
    # Consult every model in order. Ollama can then unload one HDD-backed
    # runner before loading the next, allowing all four models to contribute
    # on machines that cannot hold them simultaneously in memory.
    for model in models:
        try:
            answers[model] = _ask(base_url, api_key, model, task)
        except Exception as exc:
            answers[model] = f"(model unavailable: {exc})"
        if on_progress:
            on_progress(model, answers[model])
    dossier = "\n\n".join(f"[{model}]\n{answer}" for model, answer in answers.items())
    synthesis = ("You are the final editor. Combine the panel's answers into the best possible response. "
                 "Resolve disagreements, avoid repetition, state uncertainty, and give actionable conclusions.\n\n"
                 f"User request:\n{prompt}\n\nPanel answers:\n{dossier}")
    final_model = "qwen3.5:9b" if "qwen3.5:9b" in models else models[0]
    try:
        final = _ask(base_url, api_key, final_model, synthesis, timeout=300)
    except Exception:
        final = max(answers.values(), key=len) if answers else "No model returned an answer."
    return final, answers
