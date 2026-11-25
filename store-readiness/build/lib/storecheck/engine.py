from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .checks import CHECKS
from .checks_extra import CHECKS_EXTRA
from .discover import Project, discover

CHECKS = {**CHECKS, **CHECKS_EXTRA}      # one registry; checks_extra imports checks, never the reverse
RULES_DIR = Path(__file__).parent / "rules"
SEVERITY_ORDER = {"blocker": 0, "likely": 1, "advisory": 2}


@dataclass
class Finding:
    rule_id: str
    store: str
    severity: str
    title: str
    location: str
    detail: str
    fix: str
    source: str
    verified: str


def load_rules(extra_dir: Path | None = None) -> list[dict]:
    rules = []
    for d in [RULES_DIR] + ([extra_dir] if extra_dir else []):
        for f in sorted(Path(d).glob("*.json")):
            rules.extend(json.loads(f.read_text(encoding="utf-8"))["rules"])
    return rules


def run(project: Project, rules: list[dict], store: str = "both") -> list[Finding]:
    findings: list[Finding] = []
    project.passed = []
    for r in rules:
        if store != "both" and r["store"] not in (store, "both"):
            continue
        if r["applies_to"] == "android" and not project.has_android:
            continue
        if r["applies_to"] == "ios" and not project.has_ios:
            continue
        if r["applies_to"] == "mobile" and not (project.has_android or project.has_ios):
            continue
        check = CHECKS[r["check"]["type"]]
        params = {k: v for k, v in r["check"].items() if k != "type"}
        hits = check(project, params)
        if not hits:
            project.passed.append((r["id"], r["title"]))
        for hit in hits:
            loc, detail = hit[0], hit[1]
            sev = hit[2] if len(hit) > 2 else r["severity"]
            findings.append(Finding(r["id"], r["store"], sev, r["title"], loc,
                                    detail, r["fix"], r["source"], r.get("verified") or ""))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id, f.location))
    return findings


def scan(path: str, store: str = "both", rules_dir: Path | None = None):
    project = discover(path)
    return project, run(project, load_rules(rules_dir), store)


def to_json(project: Project, findings: list[Finding]) -> str:
    return json.dumps({
        "frameworks": sorted(project.frameworks),
        "platforms": [n for n, on in (("android", project.has_android), ("ios", project.has_ios)) if on],
        "notes": project.notes,
        "passed": [{"rule_id": i, "title": t} for i, t in getattr(project, "passed", [])],
        "findings": [asdict(f) for f in findings],
    }, indent=2)
