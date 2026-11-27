"""Optional local-LLM assistance, always advisory and always checked by deterministic guardrails.

Two jobs, both off by default:

* **Judgment checks** (`assess`): questions a static rule cannot decide ("is this app a thin website wrapper?").
  The model gets bounded, redacted evidence excerpts and must answer in strict JSON. Every quote it cites must
  appear verbatim in the evidence it was given; a "concern" with no grounded quote is downgraded to "unclear".
* **Drafts and fix notes** (`draft_listing`, `fix_notes`, `privacy_policy_text`): text for the developer to
  edit. Each draft is validated against the stores' own limits and policy wording before it is shown.

The model never adds, removes or changes a scanner finding, and nothing it says is a store verdict.
Nothing leaves the machine unless the endpoint is local or the caller passes `allow_remote=True`.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .engine import Finding

TOPICS = json.loads((Path(__file__).parent / "llm_topics.json").read_text(encoding="utf-8"))["topics"]
DEFAULT_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5-coder:14b"
MAX_EVIDENCE_CHARS = 3000        # per excerpt
MAX_TOTAL_CHARS = 12000          # per prompt: source code is never sent wholesale
VERDICTS = ("concern", "ok", "unclear")

SYSTEM = ("You review one narrow question about a mobile app for Google Play or the Apple App Store. "
          "Use ONLY the numbered evidence blocks you are given. Do not invent facts, do not claim approval or "
          "rejection is certain, and say 'unclear' when the evidence does not settle the question. "
          "Answer with a single JSON object and nothing else.")


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMConfig:
    url: str = DEFAULT_URL
    model: str = DEFAULT_MODEL
    timeout: int = 120
    allow_remote: bool = False
    send: Callable[[list], str] | None = None      # test hook: replaces the HTTP call

    def chat(self, system: str, user: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.send:
            return self.send(messages)
        if not is_local(self.url) and not self.allow_remote:
            raise LLMUnavailable(f"{urllib.parse.urlparse(self.url).hostname} is not a local address; "
                                 "pass --allow-remote-llm to send evidence to it")
        req = urllib.request.Request(
            self.url.rstrip("/") + "/chat/completions",
            data=json.dumps({"model": self.model, "messages": messages, "temperature": 0}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except Exception as e:                      # advisory feature: never break the scan
            raise LLMUnavailable(str(e)) from e


def is_local(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


# ----------------------------------------------------------------------------------- redaction
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test)?[-_]?[0-9A-Za-z]{20,}\b"),
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}\b"),
    re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"(?i)\b((?:api[_-]?key|secret|token|passw(?:or)?d|client[_-]?secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]{6,}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
]


def redact(text: str) -> str:
    for rx in _SECRETS:
        text = rx.sub(lambda m: (m.group(1) if m.groups() and m.group(1) else "") + "[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------------- evidence
@dataclass
class Evidence:
    label: str
    text: str


def collect_evidence(project, topic: dict) -> list[Evidence]:
    """Bounded, redacted excerpts for one topic. Which files count is set by the topic's `evidence` entries."""
    out: list[Evidence] = []
    budget = MAX_TOTAL_CHARS
    for spec in topic["evidence"]:
        kind = spec["kind"]
        found: list[tuple[str, str]] = []
        if kind == "files":
            rx = re.compile(spec["name"], re.I)
            for name, text, is_lock in project.texts:
                if is_lock or not rx.search(name.replace("\\", "/")):
                    continue
                found.append((name, text))
        elif kind == "readme":
            root = Path(project.root)
            if root.is_dir():
                for f in sorted(root.iterdir()):
                    if f.is_file() and f.name.lower().startswith("readme"):
                        found.append((f.name, f.read_text(encoding="utf-8", errors="ignore")))
                        break
        elif kind == "listing":
            for f in project.listing_files:
                found.append((f.relative_to(project.root).as_posix(), f.read_text(encoding="utf-8", errors="ignore")))
        elif kind == "permissions":
            lines = []
            from .checks import ANDROID, _manifest_roots
            for m, root in _manifest_roots(project):
                lines += [f"{m}: {el.get(ANDROID + 'name', '')}" for el in root.iter("uses-permission")]
            for label, d in project.plists:
                lines += [f"{label}: {k} = {str(v)[:200]}" for k, v in d.items() if k.endswith("UsageDescription")]
            if lines:
                found.append(("permissions and usage strings", "\n".join(lines)))
        elif kind == "signal":
            rx = re.compile(spec["pattern"])
            for name, text, is_lock in project.texts:
                if is_lock:
                    continue
                for m in rx.finditer(text):
                    s = max(0, m.start() - 160)
                    found.append((name, text[s:m.end() + 240]))
                    break
        for name, text in found[: spec.get("max_files", 3)]:
            clean = redact(text)[: min(MAX_EVIDENCE_CHARS, spec.get("max_chars", MAX_EVIDENCE_CHARS), budget)]
            if clean.strip():
                out.append(Evidence(name, clean))
                budget -= len(clean)
            if budget <= 0:
                return out
    return out


def _numbered(evidence: list[Evidence]) -> str:
    return "\n\n".join(f"[E{i}] {e.label}\n{e.text}" for i, e in enumerate(evidence, 1))


# ------------------------------------------------------------------------------------ parsing
def parse_json(raw: str):
    """The first JSON object in the reply (models wrap it in fences or chatter); None if there is none."""
    raw = re.sub(r"```(?:json)?", "", raw)
    start = raw.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except ValueError:
                    return None
    return None


_CERTAINTY = re.compile(r"(?i)\b(guarantee[sd]?|will (?:definitely |certainly )?be (?:approved|rejected|accepted)|"
                        r"cannot be rejected|100% (?:safe|compliant)|fully compliant)\b")
_DANGEROUS = re.compile(r"(?i)\brm\s+-rf\b|curl[^|\n]*\|\s*(?:ba)?sh|\bsudo\b|chmod\s+777|--no-verify|disable (?:ssl|tls|certificate)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------- judgment checks
def assess(project, topic_id: str, cfg: LLMConfig) -> dict:
    """One judgment question. Returns a result dict; `status` says whether guardrails changed the answer."""
    topic = next(t for t in TOPICS if t["id"] == topic_id)
    res = {"topic": topic_id, "store": topic["store"], "source": topic["source"], "question": topic["question"],
           "verdict": "unclear", "reason": "", "evidence": [], "model": cfg.model, "status": "ok", "note": "",
           "advisory": True}
    evidence = collect_evidence(project, topic)
    if not evidence:
        return {**res, "status": "skipped", "note": "no evidence of the kind this question needs was found"}
    prompt = (f"Question: {topic['question']}\nRubric: {topic['rubric']}\n\nEvidence:\n{_numbered(evidence)}\n\n"
              'Reply as JSON: {"verdict": "concern" | "ok" | "unclear", "reason": "<=2 sentences", '
              '"evidence": ["<exact quote copied from the evidence>", ...]}')
    try:
        raw = cfg.chat(SYSTEM, prompt)
    except LLMUnavailable as e:
        return {**res, "status": "unavailable", "note": f"model not reachable: {e}"}
    return _validate_assessment(res, raw, evidence)


def _validate_assessment(res: dict, raw: str, evidence: list[Evidence]) -> dict:
    data = parse_json(raw)
    if not isinstance(data, dict) or data.get("verdict") not in VERDICTS:
        return {**res, "status": "rejected", "note": "reply was not the requested JSON; ignored"}
    reason = str(data.get("reason", ""))[:600]
    if _CERTAINTY.search(reason):
        return {**res, "status": "rejected", "note": "reply claimed certainty about store approval; ignored"}
    quotes = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    grounded = []
    for q in quotes:
        nq = _norm(str(q))
        if len(nq) < 8:
            continue
        for e in evidence:
            if nq in _norm(e.text):
                grounded.append({"quote": str(q)[:300], "file": e.label})
                break
    verdict, status, note = data["verdict"], "ok", ""
    if verdict == "concern" and not grounded:
        verdict, status = "unclear", "downgraded"
        note = "the model raised a concern but cited no text found in the evidence, so it is shown as unclear"
    elif len(grounded) < len([q for q in quotes if len(_norm(str(q))) >= 8]):
        note = "some quotes were not found in the evidence and were dropped"
        status = "partial"
    return {**res, "verdict": verdict, "reason": reason, "evidence": grounded, "status": status, "note": note}


# ------------------------------------------------------------------------------ listing draft
_LISTING_LIMITS = {"title": 30, "short_description": 80, "full_description": 4000}
_RANKING = re.compile(r"(?i)#\s?1\b|\bno\.?\s?1\b|number one|app of the year|best of play|\bpopular\b|\btop[- ]rated\b|"
                      r"\bbest\b|editor'?s choice|award[- ]winning")
_PROMO = re.compile(r"(?i)\b\d{1,3}\s?%\s?off\b|free for (?:a )?limited time|cash ?back|\blimited[- ]time offer\b")
_NUMERIC_CLAIM = re.compile(r"(?i)\b\d[\d,.]*\s?(?:\+|k|m|million|thousand)?\s*(?:users|downloads|reviews|customers)\b")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def validate_listing(d: dict) -> list[str]:
    """Problems that stop a draft being shown. Limits are the ones the scanner enforces; the wording rules come
    from Google Play's Metadata policy (ranking, price/promotion and Play-program text, ALL CAPS, emoji)."""
    problems = []
    for key, limit in _LISTING_LIMITS.items():
        v = d.get(key)
        if not isinstance(v, str) or not v.strip():
            problems.append(f"{key} is missing")
            continue
        if len(v) > limit:
            problems.append(f"{key} is {len(v)} characters, limit {limit}")
        for rx, what in ((_RANKING, "ranking or award wording"), (_PROMO, "price or promotion wording"),
                         (_NUMERIC_CLAIM, "an unverifiable user or download count"), (_EMOJI, "emoji")):
            if rx.search(v):
                problems.append(f"{key} contains {what}")
        words = re.findall(r"[A-Za-z]{3,}", v)
        if len(words) >= 3 and sum(w.isupper() for w in words) / len(words) > 0.5:
            problems.append(f"{key} is mostly ALL CAPS")
        if _CERTAINTY.search(v):
            problems.append(f"{key} makes an absolute claim")
    return problems


def draft_listing(project, cfg: LLMConfig) -> dict:
    topic = next(t for t in TOPICS if t["id"] == "listing_draft")
    res = {"topic": "listing_draft", "model": cfg.model, "status": "ok", "draft": {}, "problems": [], "advisory": True}
    evidence = collect_evidence(project, topic)
    if not evidence:
        return {**res, "status": "skipped", "problems": ["no README, listing text or manifest to base a draft on"]}
    prompt = (f"{topic['question']}\nRubric: {topic['rubric']}\n\nEvidence:\n{_numbered(evidence)}\n\n"
              'Reply as JSON: {"title": "<=30 chars", "short_description": "<=80 chars", '
              '"full_description": "<=4000 chars, plain text"}. Describe only what the evidence shows.')
    try:
        raw = cfg.chat(SYSTEM, prompt)
    except LLMUnavailable as e:
        return {**res, "status": "unavailable", "problems": [f"model not reachable: {e}"]}
    data = parse_json(raw)
    if not isinstance(data, dict):
        return {**res, "status": "rejected", "problems": ["reply was not the requested JSON"]}
    draft = {k: data.get(k, "") for k in _LISTING_LIMITS}
    problems = validate_listing(draft)
    if problems:
        return {**res, "status": "rejected", "problems": problems}
    return {**res, "draft": draft}


# ----------------------------------------------------------------------------- fix notes
def fix_notes(findings: list[Finding], cfg: LLMConfig) -> dict:
    """Plain-language 'why it matters / simplest fix' per finding. Only ids the scanner reported are kept."""
    if not findings:
        return {"status": "skipped", "notes": {}, "dropped": [], "model": cfg.model}
    known = {f.rule_id for f in findings}
    body = ("Findings from a deterministic scanner:\n" +
            "\n".join(f"- {f.rule_id} [{f.severity}] {f.title}: {f.detail} (at {f.location}). Store guidance: {f.fix}"
                      for f in findings) +
            '\n\nReply as JSON: {"notes": {"<rule_id>": {"why": "<1-2 sentences>", "fix": "<simplest fix>"}}}. '
            "Only use the rule ids above; say when something is a heuristic.")
    try:
        raw = cfg.chat(SYSTEM, body)
    except LLMUnavailable as e:
        return {"status": "unavailable", "notes": {}, "dropped": [], "note": str(e), "model": cfg.model}
    data = parse_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("notes"), dict):
        return {"status": "rejected", "notes": {}, "dropped": [], "note": "reply was not the requested JSON",
                "model": cfg.model}
    notes, dropped = {}, []
    for rid, n in data["notes"].items():
        if rid not in known or not isinstance(n, dict):
            dropped.append(f"{rid}: not a finding the scanner reported")
            continue
        text = f"{n.get('why', '')} {n.get('fix', '')}"
        if _CERTAINTY.search(text) or _DANGEROUS.search(text):
            dropped.append(f"{rid}: claimed certainty or suggested an unsafe command")
            continue
        notes[rid] = {"why": str(n.get("why", ""))[:500], "fix": str(n.get("fix", ""))[:500]}
    return {"status": "ok" if notes else "rejected", "notes": notes, "dropped": dropped, "model": cfg.model}


# ------------------------------------------------------------------------------ privacy text
_INVENTED = re.compile(r"(?i)\bretain(?:ed|s)?\b|\bretention\b|\bdelete[sd]? after\b|\b\d+\s*(?:days|months|years)\b|"
                       r"\bsell\b|\bsold\b|\bshare[sd]? with\b|\bthird[- ]part(?:y|ies)\b|\badvertis")


def privacy_policy_text(draft: dict, cfg: LLMConfig) -> dict:
    """A 'Data we collect' paragraph. Rejected if it invents retention, sharing or selling statements."""
    if not draft["rows"]:
        return {"status": "skipped", "text": "", "model": cfg.model}
    lines = "\n".join(f"- {r['key']}: {r['strength']}; hints: {', '.join(r['hints']) or 'none'}" for r in draft["rows"])
    body = ("Write a short, plain-language 'Data we collect' section for a privacy policy based ONLY on this list "
            "of possibly-collected data types. Mark anything uncertain with [CONFIRM]. Do not invent purposes, "
            "retention periods or sharing practices.\n\n" + lines)
    try:
        text = cfg.chat(SYSTEM, body)
    except LLMUnavailable as e:
        return {"status": "unavailable", "text": "", "note": str(e), "model": cfg.model}
    if _INVENTED.search(text):
        return {"status": "rejected", "text": "", "model": cfg.model,
                "note": "the draft made retention, sharing or selling statements the scan cannot support"}
    if any(r["strength"].startswith("likely") for r in draft["rows"]) and "[CONFIRM]" not in text:
        return {"status": "rejected", "text": "", "model": cfg.model,
                "note": "the draft did not mark any uncertain item with [CONFIRM]"}
    return {"status": "ok", "text": text, "model": cfg.model}


# ------------------------------------------------------------------------------- rendering
def render_assessment(r: dict) -> str:
    head = f"[{r['verdict'].upper()}] {r['topic']} ({r['store']}, advisory, model {r['model']})"
    if r["status"] in ("skipped", "unavailable", "rejected"):
        return f"{head}\n  {r['status']}: {r['note']}"
    lines = [head, f"  {r['reason']}"]
    lines += [f'  evidence: "{e["quote"]}" ({e["file"]})' for e in r["evidence"]]
    if r["note"]:
        lines.append(f"  note: {r['note']}")
    lines.append(f"  source: {r['source']}")
    return "\n".join(lines)


def render_listing(r: dict) -> str:
    if r["status"] != "ok":
        return f"listing draft {r['status']}: " + "; ".join(r["problems"])
    d = r["draft"]
    return (f"Title ({len(d['title'])}/30): {d['title']}\nShort ({len(d['short_description'])}/80): "
            f"{d['short_description']}\n\n{d['full_description']}\n\n"
            "[CONFIRM] Draft only: check every claim against the app before publishing.")


def render_fix_notes(r: dict) -> str:
    if r["status"] not in ("ok",):
        return f"fix notes {r['status']}" + (f": {r.get('note', '')}" if r.get("note") else "")
    return "\n".join(f"- {rid}: {n['why']} Fix: {n['fix']}" for rid, n in r["notes"].items())


def explain(findings, url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=120) -> str:   # kept for older callers
    return render_fix_notes(fix_notes(findings, LLMConfig(url, model, timeout)))
