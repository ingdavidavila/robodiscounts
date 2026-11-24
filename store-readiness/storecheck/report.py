from __future__ import annotations

from .discover import Project
from .engine import Finding

LABEL = {"blocker": "BLOCKER ", "likely": "LIKELY  ", "advisory": "ADVISORY"}


def to_text(project: Project, findings: list[Finding]) -> str:
    plats = [n for n, on in (("android", project.has_android), ("ios", project.has_ios)) if on]
    lines = [f"Detected platforms: {', '.join(plats) or 'none'}",
             f"Frameworks: {', '.join(sorted(project.frameworks)) or 'unknown'}"]
    lines += [f"Note: {n}" for n in project.notes]
    if not findings:
        lines.append("\nNo findings. This is not a guarantee of approval.")
    for f in findings:
        lines += ["", f"[{LABEL[f.severity]}] {f.title}  ({f.rule_id}, {f.store})",
                  f"  where: {f.location}", f"  what:  {f.detail}", f"  fix:   {f.fix}",
                  f"  source: {f.source}" + (f"  (verified {f.verified})" if f.verified else "  (rule NOT yet verified against current docs)")]
    n = {s: sum(f.severity == s for f in findings) for s in LABEL}
    lines += ["", f"{n['blocker']} blocker(s), {n['likely']} likely, {n['advisory']} advisory"]
    return "\n".join(lines)
