"""Scorecard: measure the project against the framework in framework/FRAMEWORK.md.

    python -m storecheck.measure --log "what changed" --review "does the framework still fit the goal?"
    python -m storecheck.measure --corpus PATH --log ... --review ...   # include the real-app benchmark

Everything here is computed from files in the repository and from running the tool on the benchmark. Scores that
depend on a judgment (the requirement catalog, the labels) are recorded in data files with their evidence, never in
this script. Each run is appended to framework/history.jsonl and compared with the previous run.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .engine import load_rules, scan

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "framework"
TODAY = dt.date(2026, 11, 25)

# weights (sum 100) and pass gates are defined in framework/FRAMEWORK.md; change both together, with a log entry
# 2026-11-27: D9 (AI assistance) added at the owner's request; D1 and D2 gave up 5 points each to make room.
WEIGHTS = {"D1": 20, "D2": 20, "D3": 10, "D4": 10, "D5": 10, "D6": 10, "D7": 5, "D8": 5, "D9": 10}
GATES = {"D1": 0.80, "D2": 0.90, "D3": 0.90, "D4": 0.80, "D5": 0.75, "D6": 0.90, "D7": 1.00, "D8": 0.90, "D9": 0.80}
NAMES = {"D1": "Requirement coverage", "D2": "Correctness", "D3": "Verification", "D4": "Actionability",
         "D5": "Stack reach", "D6": "Portability and delivery", "D7": "Safety and privacy", "D8": "Robustness", "D9": "AI assistance"}
KNOWN_FEATURES = {"privacy_draft", "rating_hints", "privacy_draft.tracking"}
FRESH_DAYS = 90


def _load(name: str):
    return json.loads((FW / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------- D1
def d1_coverage() -> dict:
    cat = json.loads((ROOT / "storecheck" / "requirements.json").read_text(encoding="utf-8"))
    rule_ids = {r["id"] for r in load_rules()}
    items = cat["items"]
    by = {"automated": 0, "partial": 0, "unmapped": 0, "not_checkable": 0}
    broken = []
    for it in items:
        by[it["class"]] += 1
        if it["class"] in ("automated", "partial"):
            refs = it.get("rules", [])
            if not refs or any(r not in rule_ids and r not in KNOWN_FEATURES for r in refs):
                broken.append(it["id"])
        if it["class"] == "not_checkable" and not it.get("reason"):
            broken.append(it["id"])
    checkable = len(items) - by["not_checkable"]
    static = (by["automated"] + 0.5 * by["partial"]) / checkable if checkable else 0.0
    from .checklist import checklist_ids
    emitted = checklist_ids(None)                     # what the feature really lists for a project on both stores
    nc = [i for i in items if i["class"] == "not_checkable"]
    checklist = sum(1 for i in nc if i["id"] in emitted) / len(nc) if nc else 1.0
    excluded_share = by["not_checkable"] / len(items)
    score = 0.7 * static + 0.3 * checklist
    if excluded_share > 0.6 or broken:
        score *= 0.5            # too much of the catalog excluded, or the catalog is inconsistent
    return {"score": score, "static_coverage": static, "checklist_coverage": checklist, "counts": by,
            "items": len(items), "excluded_share": excluded_share, "broken_refs": broken}


# ---------------------------------------------------------------------------------------------- D2
def _write_case(root: Path, files: dict) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(content["b64"]) if isinstance(content, dict) else content.encode())


def run_synthetic() -> dict:
    cases = _load("benchmark/synthetic.json")["cases"]
    rules = {r["id"] for r in load_rules()}
    found_total = found_ok = not_total = not_bad = crashes = 0
    note_total = note_ok = 0
    failures, pos, neg = [], set(), set()
    t0 = time.time()
    for c in cases:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_case(root, c["files"])
            try:
                project, findings = scan(str(root), c.get("scan", "both"))
            except Exception as e:      # a crash is a robustness failure
                crashes += 1
                failures.append(f"{c['id']}: crashed ({type(e).__name__})")
                found_total += len(c["must_find"])
                not_total += len(c["must_not"])
                continue
            ids = {f.rule_id for f in findings}
            for r in c["must_find"]:
                found_total += 1
                pos.add(r)
                if r in ids:
                    found_ok += 1
                else:
                    failures.append(f"{c['id']}: missed {r}")
            for r in c["must_not"]:
                not_total += 1
                neg.add(r)
                if r in ids:
                    not_bad += 1
                    failures.append(f"{c['id']}: false positive {r}")
            for rid, limit in c.get("max_count", {}).items():
                found_total += 1
                if sum(1 for f in findings if f.rule_id == rid) <= limit:
                    found_ok += 1
                else:
                    failures.append(f"{c['id']}: {rid} reported more than {limit} time(s)")
            for n in c.get("must_note", []):
                note_total += 1
                if any(n in x for x in project.notes):
                    note_ok += 1
                else:
                    failures.append(f"{c['id']}: no note containing {n!r}")
    recall = found_ok / found_total if found_total else 0.0
    fpr = not_bad / not_total if not_total else 1.0
    both = len(rules & pos & neg)
    rule_cov = both / len(rules)
    return {"cases": len(cases), "recall": recall, "false_positive_rate": fpr, "rule_case_coverage": rule_cov,
            "rules_without_both": sorted(rules - (pos & neg)), "crashes": crashes, "notes_ok": (note_ok, note_total),
            "failures": failures, "seconds": time.time() - t0,
            "score": 0.4 * recall + 0.4 * (1 - fpr) + 0.2 * rule_cov}


def run_real(corpus: Path) -> dict:
    manifest = _load("benchmark/real_apps.json")
    tp = fp = unverified = unlabeled = total = crashes = 0
    mf_total = mf_ok = mn_viol = 0
    slowest = 0.0
    per_app, problems = {}, []
    for app in manifest["apps"]:
        path = corpus / app["name"]
        if not path.exists():
            problems.append(f"{app['name']}: not in corpus")
            continue
        t0 = time.time()
        try:
            _, findings = scan(str(path))
        except Exception as e:
            crashes += 1
            problems.append(f"{app['name']}: crashed ({type(e).__name__})")
            continue
        slowest = max(slowest, time.time() - t0)
        labels = [dict(l, used=False) for l in app["labels"]]
        a_tp = a_fp = a_un = a_unl = 0
        for f in findings:
            total += 1
            lab = next((l for l in labels if not l["used"] and l["rule"] == f.rule_id and l["loc"] in f.location), None)
            if lab is None:
                unlabeled += 1
                a_unl += 1
                problems.append(f"{app['name']}: unlabeled {f.rule_id} at {f.location}")
                continue
            lab["used"] = True
            if lab["verdict"] == "tp":
                tp += 1
                a_tp += 1
            elif lab["verdict"] == "fp":
                fp += 1
                a_fp += 1
            else:
                unverified += 1
                a_un += 1
        for m in app["must_find"]:
            mf_total += 1
            if any(f.rule_id == m["rule"] and m["loc"] in f.location for f in findings):
                mf_ok += 1
            else:
                problems.append(f"{app['name']}: missed known issue {m['rule']} {m['loc']}")
        for m in app["must_not"]:
            if any(f.rule_id == m["rule"] and m["loc"] in f.location for f in findings):
                mn_viol += 1
                fp += 1
                problems.append(f"{app['name']}: known false positive is back: {m['rule']} {m['loc']}")
        per_app[app["name"]] = {"tp": a_tp, "fp": a_fp, "unverified": a_un, "unlabeled": a_unl}
    verified_fraction = (tp + fp) / total if total else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = mf_ok / mf_total if mf_total else 0.0
    score = precision * recall * min(1.0, verified_fraction / 0.8)
    if unlabeled:
        score *= 0.5            # new, untriaged findings: the result cannot be trusted until they are labeled
    return {"score": score, "precision": precision, "known_issue_recall": recall, "verified_fraction": verified_fraction,
            "findings": total, "tp": tp, "fp": fp, "unverified": unverified, "unlabeled": unlabeled,
            "crashes": crashes, "slowest_seconds": slowest, "problems": problems, "per_app": per_app}


def readers_verified() -> dict:
    rs = _load("readers.json")["readers"]
    ok = [r for r in rs if r["status"] == "verified" and r.get("reference") and (ROOT / r["test"]).exists()]
    return {"score": len(ok) / len(rs), "verified": [r["reader"] for r in ok],
            "unverified": [r["reader"] for r in rs if r not in ok]}


def d2_correctness(syn: dict, real: dict | None) -> dict:
    rd = readers_verified()
    score = 0.45 * syn["score"] + (0.45 * real["score"] if real else 0.0) + 0.10 * rd["score"]
    return {"score": score, "synthetic": syn, "real": real, "real_measured": real is not None, "readers": rd}


# ---------------------------------------------------------------------------------------------- D3
def d3_verification() -> dict:
    rules = load_rules()
    full = part = none = fresh = 0
    for r in rules:
        v = (r.get("verified") or "").strip()
        if not v:
            none += 1
            continue
        if "partly" in v:
            part += 1
        else:
            full += 1
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
        if m and (TODAY - dt.date(*map(int, m.groups()))).days <= FRESH_DAYS:
            fresh += 1
    n = len(rules)
    rules_score = (full + 0.5 * part) / n
    sdk = json.loads((ROOT / "storecheck" / "privacy_data.json").read_text(encoding="utf-8"))["signals"]
    sdk_verified = sum(1 for s in sdk if s.get("verified")) / len(sdk)
    score = 0.6 * rules_score + 0.2 * (fresh / n) + 0.2 * sdk_verified
    return {"score": score, "rules": n, "fully_verified": full, "partly_verified": part, "unverified": none,
            "fresh_within_days": FRESH_DAYS, "fresh": fresh, "sdk_groups": len(sdk),
            "sdk_groups_verified": round(sdk_verified * len(sdk))}


# ---------------------------------------------------------------------------------------------- D4
def d4_actionability() -> dict:
    from .fixes import FIXABLE_RULES
    rules = load_rules()
    ok = sum(1 for r in rules if r.get("fix") and str(r.get("source", "")).startswith("https://")
             and r.get("severity") in ("blocker", "likely", "advisory") and "verified" in r)
    schema = ok / len(rules)
    fixable = len({r["id"] for r in rules} & set(FIXABLE_RULES)) / len(rules)
    return {"score": 0.5 * schema + 0.5 * min(1.0, fixable / 0.30), "schema_complete": schema,
            "auto_fixable_share": fixable, "auto_fixable_target": 0.30}


# ---------------------------------------------------------------------------------------------- D5
def d5_reach() -> dict:
    m = _load("benchmark/real_apps.json")
    targets = m["target_stacks"]
    count = {s: 0 for s in targets}
    for a in m["apps"]:
        count[a["stack"]] = count.get(a["stack"], 0) + 1
    got = sum(min(1.0, count[s] / 2) for s in targets)
    return {"score": got / len(targets), "stacks_with_2plus_apps": [s for s in targets if count[s] >= 2],
            "stacks_with_1_app": [s for s in targets if count[s] == 1], "stacks_untested": [s for s in targets if count[s] == 0]}


# ---------------------------------------------------------------------------------------------- D6
def _pip_install_works() -> bool:
    if not (ROOT / "pyproject.toml").exists():
        return False
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--target", d, str(ROOT)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not (Path(d) / "storecheck").exists():
            return False
        # the installed copy must work on its own: rules, catalog, privacy data and the GUI page are package data
        code = ("import storecheck, storecheck.gui as g, storecheck.checklist as c, json, pathlib;"
                "from storecheck.engine import load_rules;"
                "assert len(load_rules())>20 and c.build_checklist()['ids'] and 'Store Check' in g.PAGE;"
                "from storecheck.engine import scan;import tempfile;scan(tempfile.mkdtemp())")
        env = {**__import__("os").environ, "PYTHONPATH": d}
        return subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=d).returncode == 0


def d6_portability() -> dict:
    wf = ROOT.parent / ".github" / "workflows"
    ci_text = " ".join(p.read_text(encoding="utf-8") for p in wf.glob("*.y*ml")) if wf.exists() else ""
    ci = all(x in ci_text for x in ("ubuntu", "macos", "windows"))
    observed = _load("observations.json")["os_observed"]
    stdlib_only = not (ROOT / "requirements.txt").exists() or not (ROOT / "requirements.txt").read_text(encoding="utf-8").strip()
    parts = {"pyproject": (ROOT / "pyproject.toml").exists(), "pip_install": _pip_install_works(),
             "ci_three_os": ci, "os_observed": min(1.0, len(set(observed)) / 3),
             "gui_test": (ROOT / "tests" / "test_gui.py").exists(), "stdlib_only": stdlib_only}
    weights = {"pyproject": .15, "pip_install": .25, "ci_three_os": .2, "os_observed": .2, "gui_test": .1, "stdlib_only": .1}
    return {"score": sum(weights[k] * float(v) for k, v in parts.items()), "parts": parts, "os_observed": observed}


# ---------------------------------------------------------------------------------------------- D7
NETWORK_RX = re.compile(r"^\s*(?:import|from)\s+(urllib|http\.client|socket|requests|ftplib|smtplib)\b", re.M)


def d7_safety() -> dict:
    pkg = ROOT / "storecheck"
    allowed = {"llm.py", "gui.py"}
    net_modules = {p.name for p in pkg.glob("*.py") if NETWORK_RX.search(p.read_text(encoding="utf-8"))}
    gui = (pkg / "gui.py").read_text(encoding="utf-8")
    fixes = (pkg / "fixes.py").read_text(encoding="utf-8")
    checks = {
        "network_only_in_llm_and_gui": net_modules <= allowed,
        "fixes_never_write_project_files": not re.search(r"write_text|write_bytes|open\([^)]*[\"']w", fixes),
        "gui_localhost_and_token": "127.0.0.1" in gui and "compare_digest" in gui,
        "github_url_allowlist": "GITHUB_RX" in gui and "https://github.com/" in gui,
        "gui_tests_exist": (ROOT / "tests" / "test_gui.py").exists(),
        "llm_local_only_by_default": "allow_remote" in (pkg / "llm.py").read_text(encoding="utf-8")
        and dict(__import__("storecheck.llm_selftest", fromlist=["run"]).run()).get("remote_endpoint_refused_by_default", False),
    }
    return {"score": sum(checks.values()) / len(checks), "checks": checks, "network_modules": sorted(net_modules)}


# ---------------------------------------------------------------------------------------------- D8
def d8_robustness(syn: dict, real: dict | None) -> dict:
    crash_free = 1.0 if syn["crashes"] == 0 and (real is None or real["crashes"] == 0) else 0.0
    n_ok, n_total = syn["notes_ok"]
    notes = n_ok / n_total if n_total else 0.0
    slowest = real["slowest_seconds"] if real else syn["seconds"] / max(1, syn["cases"])
    perf = min(1.0, 10.0 / slowest) if slowest > 0 else 1.0
    return {"score": (crash_free + notes + perf) / 3, "crash_free": crash_free, "notes_on_skip": notes,
            "slowest_scan_seconds": slowest, "perf_measured_on": "corpus" if real else "synthetic (corpus not run)"}


# ---------------------------------------------------------------------------------------------- D9
def run_live_eval(url: str, model: str) -> dict:
    """Ask a real model the benchmark questions. Returns {model, date, correct, total, cases} or raises."""
    from . import llm
    from .discover import discover
    from .llm_selftest import _project
    cfg = llm.LLMConfig(url, model, timeout=300)
    cases, correct = [], 0
    for c in _load("benchmark/llm_eval.json")["cases"]:
        project = discover(_project(c["files"]))
        if c["topic"] == "listing_draft":
            r = llm.draft_listing(project, cfg)
            got, ok = r["status"], r["status"] == "ok"
        else:
            r = llm.assess(project, c["topic"], cfg)
            got = r["verdict"]
            ok = r["status"] in ("ok", "partial") and got == c["expect"] and (got != "concern" or bool(r["evidence"]))
        if r["status"] == "unavailable":
            raise RuntimeError(f"model not reachable: {r.get('note') or r.get('problems')}")
        correct += ok
        cases.append({"id": c["id"], "expect": c["expect"], "got": got, "ok": ok})
    return {"model": model, "date": TODAY.isoformat(), "correct": correct, "total": len(cases), "cases": cases}


def d9_assist() -> dict:
    """0.5 guardrails hold against misbehaving fake models, 0.2 planned AI jobs built and covered by eval cases,
    0.3 a recorded live-model evaluation (unmeasured counts as 0). The live part says how good one specific
    model was on this benchmark; the guardrail part says the layer is safe whichever model is behind it."""
    from . import llm, llm_selftest
    guard = llm_selftest.run()
    g = sum(ok for _, ok in guard) / len(guard)
    eval_cases = _load("benchmark/llm_eval.json")["cases"]
    per_topic = {}
    for c in eval_cases:
        per_topic[c["topic"]] = per_topic.get(c["topic"], 0) + 1
    judgment = [t["id"] for t in llm.TOPICS if t["kind"] == "judgment"]
    built = [t for t in judgment if per_topic.get(t, 0) >= 2] + ["listing_draft"] * (per_topic.get("listing_draft", 0) >= 1)
    guard_names = {n for n, _ in guard}
    built += [x for x, key in (("fix_notes", "fix_notes_filtering"), ("privacy_wording", "privacy_text_guards"))
              if key in guard_names]
    planned = len(judgment) + 3
    cov = len(built) / planned
    live = _load("observations.json").get("llm_live")
    live_score = live["correct"] / live["total"] if live and live.get("total") else 0.0
    return {"score": 0.5 * g + 0.2 * cov + 0.3 * live_score, "guardrails": f"{sum(ok for _, ok in guard)}/{len(guard)}",
            "guardrail_failures": [n for n, ok in guard if not ok], "coverage": f"{len(built)}/{planned}",
            "live": live if live else "NOT MEASURED (counted as 0; run with --llm-url and --llm-model)"}


# ---------------------------------------------------------------------------------------------- run
def measure(corpus: Path | None = None) -> dict:
    syn = run_synthetic()
    real = run_real(corpus) if corpus else None
    dims = {"D1": d1_coverage(), "D2": d2_correctness(syn, real), "D3": d3_verification(), "D4": d4_actionability(),
            "D5": d5_reach(), "D6": d6_portability(), "D7": d7_safety(), "D8": d8_robustness(syn, real),
            "D9": d9_assist()}
    overall = sum(WEIGHTS[k] * min(1.0, dims[k]["score"]) for k in WEIGHTS) / sum(WEIGHTS.values())
    gates = {k: dims[k]["score"] >= GATES[k] for k in GATES}
    return {"overall": overall, "dims": dims, "gates": gates, "goal_achieved": all(gates.values())}


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _previous() -> dict | None:
    h = FW / "history.jsonl"
    if not h.exists() or not h.read_text(encoding="utf-8").strip():
        return None
    return json.loads(h.read_text(encoding="utf-8").strip().splitlines()[-1])


def render(res: dict, prev: dict | None) -> str:
    L = [f"SCORECARD  overall {res['overall'] * 100:.1f}%   goal achieved: {'YES' if res['goal_achieved'] else 'NO'}",
         f"{'':3}{'dimension':26}{'weight':>7}{'score':>8}{'gate':>7}{'pass':>6}{'change':>9}"]
    for k in WEIGHTS:
        s = res["dims"][k]["score"]
        d = ""
        if prev and k in prev["scores"]:
            delta = (s - prev["scores"][k]) * 100
            d = f"{delta:+.1f}" if abs(delta) >= 0.05 else "="
        L.append(f"{k:3}{NAMES[k]:26}{WEIGHTS[k]:>7}{s * 100:>7.1f}%{GATES[k] * 100:>6.0f}%{'yes' if res['gates'][k] else 'no':>6}{d:>9}")
    if prev:
        L.append(f"previous overall {prev['overall'] * 100:.1f}% ({prev['ts']} @ {prev['commit']}: {prev['log']})")
    d2 = res["dims"]["D2"]
    if d2.get("readers", {}).get("unverified"):
        L.append("D2 readers not yet verified against an independent reference: " + ", ".join(d2["readers"]["unverified"]))
    d9 = res["dims"]["D9"]
    L.append(f"D9 guardrails {d9['guardrails']}, jobs covered {d9['coverage']}, live model: " +
             (f"{d9['live']['model']} {d9['live']['correct']}/{d9['live']['total']} on {d9['live']['date']}"
              if isinstance(d9["live"], dict) else d9["live"]))
    L.append("D2 real corpus: " + ("measured" if d2["real_measured"] else "NOT MEASURED (pass --corpus; counted as 0)"))
    for f in d2["synthetic"]["failures"][:12]:
        L.append("  synthetic failure: " + f)
    if d2["real"]:
        for p in d2["real"]["problems"][:12]:
            L.append("  real corpus: " + p)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="storecheck.measure")
    ap.add_argument("--corpus", type=Path, help="directory containing the benchmark apps (see framework/benchmark/fetch.sh)")
    ap.add_argument("--log", help="what work was just done (required to record a run)")
    ap.add_argument("--review", help="framework re-evaluation: does the framework still fit the goal? (required to record)")
    ap.add_argument("--no-history", action="store_true", help="measure without recording")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--llm-url", help="run the live AI evaluation against this OpenAI-compatible endpoint and record it")
    ap.add_argument("--llm-model", default=None, help="model name for --llm-url")
    a = ap.parse_args(argv)
    if a.llm_url:
        live = run_live_eval(a.llm_url, a.llm_model or "qwen2.5-coder:14b")
        obs = _load("observations.json")
        obs["llm_live"] = live
        (FW / "observations.json").write_text(json.dumps(obs, indent=1), encoding="utf-8")
        print(f"live AI evaluation recorded: {live['model']} {live['correct']}/{live['total']}")
    if not a.no_history and not (a.log and a.review):
        ap.error("--log and --review are required to record a run (or pass --no-history)")
    res = measure(a.corpus)
    prev = _previous()
    print(json.dumps(res, indent=1) if a.json else render(res, prev))
    if not a.no_history:
        entry = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "commit": _commit(), "log": a.log,
                 "overall": res["overall"], "scores": {k: res["dims"][k]["score"] for k in WEIGHTS},
                 "real_measured": res["dims"]["D2"]["real_measured"], "goal_achieved": res["goal_achieved"]}
        with open(FW / "history.jsonl", "a", encoding="utf-8") as h:
            h.write(json.dumps(entry) + "\n")
        with open(FW / "REVIEW_LOG.md", "a", encoding="utf-8") as r:
            r.write(f"\n## {entry['ts']} @ {entry['commit']}: {a.log}\n\nOverall {res['overall'] * 100:.1f}%. "
                    f"Framework re-evaluation: {a.review}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
