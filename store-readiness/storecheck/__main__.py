from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import checklist, fixes, llm, privacy, report
from .engine import scan, to_json


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="storecheck",
                                 description="Check an app against Google Play and App Store requirements.")
    ap.add_argument("path", help="project directory, or a built .apk/.aab/.ipa")
    ap.add_argument("--store", choices=["google", "apple", "both"], default="both")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--rules-dir", type=Path, help="extra rules directory (JSON)")
    ap.add_argument("--privacy-draft", action="store_true",
                    help="print a Data safety / App Privacy label draft instead of the scan report")
    ap.add_argument("--checklist", action="store_true",
                    help="print the manual checklist: what storecheck cannot decide or does not check yet")
    ap.add_argument("--fix-plan", metavar="FILE",
                    help="write a unified diff of safe fixes to FILE ('-' for stdout); never edits your files")
    ap.add_argument("--explain", action="store_true", help="add advisory notes from a local LLM")
    ap.add_argument("--assess", nargs="*", metavar="TOPIC",
                    help="ask a local LLM the judgment questions a static rule cannot decide "
                         f"({', '.join(t['id'] for t in llm.TOPICS if t['kind'] == 'judgment')}; none named = all)")
    ap.add_argument("--draft-listing", action="store_true",
                    help="draft a Play store title and descriptions with a local LLM, checked against the limits")
    ap.add_argument("--llm-url", default=llm.DEFAULT_URL)
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--allow-remote-llm", action="store_true",
                    help="allow a non-local LLM endpoint (evidence excerpts leave this machine)")
    a = ap.parse_args(argv)
    cfg = llm.LLMConfig(a.llm_url, a.model, allow_remote=a.allow_remote_llm)
    project, findings = scan(a.path, a.store, a.rules_dir)
    if a.checklist:
        print(checklist.to_markdown(checklist.build_checklist(project)))
        return 0
    if a.fix_plan:
        ed, skipped = fixes.build_fixes(project, findings)
        patch = fixes.to_patch(ed)
        if a.fix_plan == "-":
            print(patch)
        else:
            Path(a.fix_plan).write_bytes(patch.encode("utf-8"))   # bytes: no newline translation on Windows
            n = len([r for r in ed.text if ed.text[r] != ed.orig[r]])
            print(f"Wrote {a.fix_plan}: {n} file(s) changed. Review, then apply with: git apply {a.fix_plan}")
        if skipped:
            print("Not fixed automatically (need a human decision):\n  " + "\n  ".join(skipped), file=sys.stderr)
        return 0
    if a.assess is not None or a.draft_listing:
        import json as _json
        out = []
        if a.assess is not None:
            ids = a.assess or [t["id"] for t in llm.TOPICS if t["kind"] == "judgment"]
            unknown = [i for i in ids if i not in {t["id"] for t in llm.TOPICS if t["kind"] == "judgment"}]
            if unknown:
                print("unknown topic: " + ", ".join(unknown), file=sys.stderr)
                return 2
            out += [llm.assess(project, i, cfg) for i in ids]
        listing = llm.draft_listing(project, cfg) if a.draft_listing else None
        if a.format == "json":
            print(_json.dumps({"assessments": out, "listing": listing}, indent=2))
        else:
            print("\n\n".join(llm.render_assessment(r) for r in out))
            if listing:
                print(llm.render_listing(listing))
        return 0
    if a.privacy_draft:
        import json
        draft = privacy.build_draft(project)
        print(json.dumps(draft, indent=2) if a.format == "json" else privacy.to_markdown(draft))
        if a.explain:
            r = llm.privacy_policy_text(draft, cfg)
            print("\n--- AI notes (advisory, from a local model) ---\n" +
                  (r["text"] or f"privacy wording {r['status']}: {r.get('note', '')}"))
        return 0
    print(to_json(project, findings) if a.format == "json" else report.to_text(project, findings))
    if a.explain:
        print("\n--- AI notes (advisory, from a local model) ---\n" +
              llm.render_fix_notes(llm.fix_notes(findings, cfg)))
    return 1 if any(f.severity == "blocker" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
