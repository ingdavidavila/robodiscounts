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
    return _chat(body, url, model, timeout)


def _chat(body: str, url: str, model: str, timeout: int) -> str:
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": body}]}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:  # advisory feature: never break the scan
        return f"(LLM explanation unavailable: {e})"


def privacy_policy_text(draft: dict, url: str = "http://localhost:11434/v1",
                        model: str = "qwen2.5-coder:14b", timeout: int = 120) -> str:
    """Ask a local model for a plain-language 'data we collect' paragraph. Advisory draft only."""
    if not draft["rows"]:
        return ""
    lines = "\n".join(f"- {r['key']}: {r['strength']}; hints: {', '.join(r['hints']) or 'none'}"
                      for r in draft["rows"])
    body = ("Write a short, plain-language 'Data we collect' section for a privacy policy based ONLY "
            "on this list of possibly-collected data types. Mark anything uncertain with [CONFIRM]. "
            "Do not invent purposes, retention periods or sharing practices.\n\n" + lines)
    return _chat(body, url, model, timeout)
    return _chat(body, url, model, timeout)
