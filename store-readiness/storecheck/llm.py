"""Optional local-LLM explanation via any OpenAI-compatible endpoint (Ollama, llama.cpp, LM Studio)."""
from __future__ import annotations

import json
import urllib.request

from .engine import Finding

PROMPT = ("You help developers prepare an app for Google Play and the Apple App Store. "
          "Below are findings from a deterministic scanner. For each, explain in one or two plain "
          "sentences why a store reviewer cares and the simplest fix. Do not invent new findings, "
          "do not claim approval is guaranteed, and say when something is a heuristic.\n\n")


def explain(findings: list[Finding], url: str = "http://localhost:11434/v1",
            model: str = "qwen2.5-coder:14b", timeout: int = 120) -> str:
    if not findings:
        return ""
    body = PROMPT + "\n".join(f"- {f.rule_id} [{f.severity}] {f.title}: {f.detail} (at {f.location})"
                              for f in findings)
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": body}]}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:  # advisory feature: never break the scan
        return f"(LLM explanation unavailable: {e})"
