from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import fixes, llm, privacy, report
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
    ap.add_argument("--fix-plan", metavar="FILE",
                    help="write a unified diff of safe fixes to FILE ('-' for stdout); never edits your files")
    ap.add_argument("--explain", action="store_true", help="add advisory notes from a local LLM")
    ap.add_argument("--llm-url", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="qwen2.5-coder:14b")
    a = ap.parse_args(argv)
    project, findings = scan(a.path, a.store, a.rules_dir)
    if a.fix_plan:
        ed, skipped = fixes.build_fixes(project, findings)
        patch = fixes.to_patch(ed)
        if a.fix_plan == "-":
            print(patch)
        else:
            Path(a.fix_plan).write_text(patch)
            n = len([r for r in ed.text if ed.text[r] != ed.orig[r]])
            print(f"Wrote {a.fix_plan}: {n} file(s) changed. Review, then apply with: git apply {a.fix_plan}")
        if skipped:
            print("Not fixed automatically (need a human decision):\n  " + "\n  ".join(skipped), file=sys.stderr)
        return 0
    if a.privacy_draft:
        import json
        draft = privacy.build_draft(project)
        print(json.dumps(draft, indent=2) if a.format == "json" else privacy.to_markdown(draft))
        if a.explain:
            print("\n--- AI notes (advisory, from a local model) ---\n" +
                  llm.privacy_policy_text(draft, a.llm_url, a.model))
        return 0
    print(to_json(project, findings) if a.format == "json" else report.to_text(project, findings))
    if a.explain:
        print("\n--- AI notes (advisory, from a local model) ---\n" +
              llm.explain(findings, a.llm_url, a.model))
    return 1 if any(f.severity == "blocker" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
