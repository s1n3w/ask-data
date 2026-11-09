"""Minimal Ollama chat client that also reports token counts and timing."""
import time
from dataclasses import dataclass
from functools import cache

import requests

OLLAMA_URL = "http://127.0.0.1:11434"
# qwen3.6:27b replaced qwen2.5-coder:32b on 2026-10-22: more accurate on both question sets
# (86.5 vs 83 of 89 core questions, averaged over two runs), 2.7x the tokens/s, 4.6 GB less memory.
# See evals/models/2026-10-22-tuning-pass.md.
DEFAULT_MODEL = "qwen3.6:27b"
# Ollama defaults to a 32K context, which spilled the earlier 32B model onto the CPU on a 24 GB GPU.
# Our prompts are ~2K tokens, so 8K keeps everything in VRAM (~4x faster).
NUM_CTX = 8192


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    output_tokens: int
    seconds: float
    gen_seconds: float = 0.0   # time spent generating output tokens (excludes prompt processing)


@cache
def supports_thinking(model: str) -> bool:
    """Reasoning models (e.g. qwen3) write a long hidden "thinking" pass unless it's turned off."""
    r = requests.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=60)
    r.raise_for_status()
    return "thinking" in r.json().get("capabilities", [])


def chat(messages: list[dict], model: str = DEFAULT_MODEL) -> Reply:
    started = time.time()
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    if supports_thinking(model):
        body["think"] = False  # SQL needs a direct answer; thinking makes it many times slower
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=600, json=body)
    r.raise_for_status()
    body = r.json()
    return Reply(body["message"]["content"], body.get("prompt_eval_count", 0),
                 body.get("eval_count", 0), time.time() - started, body.get("eval_duration", 0) / 1e9)


def unload(model: str) -> None:
    requests.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=120).raise_for_status()


def loaded_models() -> dict[str, dict]:
    """name -> {'size_gb', 'vram_gb'} for models currently in memory."""
    r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=30)
    r.raise_for_status()
    return {m["name"]: {"size_gb": m["size"] / 1e9, "vram_gb": m.get("size_vram", 0) / 1e9}
            for m in r.json().get("models", [])}
