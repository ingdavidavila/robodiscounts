"""Fix patches for findings with a safe, mechanical fix.

The tool never edits your files. It writes a unified diff (relative to the project root) that you can review and
apply with `git apply` or `patch -p1`. Only fixes that the official docs spell out are generated; everything else is
listed under "not fixed automatically". Usage strings come out as TODO placeholders you must replace.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from .discover import Project
from .engine import Finding, load_rules

TODO_STRING = "TODO: explain why this app needs access (required by App Review)"


def _min_target_sdk() -> int:
    for r in load_rules():
        if r["id"] == "play.target_sdk":
            return r["check"]["min_target_sdk"]
    return 36


def _min_ios() -> str:
    for r in load_rules():
        if r["id"] == "apple.deployment_target":
            return ".".join(str(x) for x in r["check"]["min_version"]) if len(r["check"]["min_version"]) > 1 \
                else str(r["check"]["min_version"][0])
    return "13.0"


class Edits:
    def __init__(self, root: Path):
        self.root = root
        self.text: dict[str, str] = {}
        self.orig: dict[str, str] = {}

    def get(self, rel: str) -> str | None:
        if rel not in self.text:
            try:
                data = (self.root / rel).read_bytes()
                if b"\0" in data[:1024]:
                    return None                      # binary plist or other non-text file
                self.orig[rel] = self.text[rel] = data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                return None
        return self.text[rel]

    def set(self, rel: str, new: str) -> None:
        self.text[rel] = new


def build_fixes(project: Project, findings: list[Finding]) -> tuple[Edits, list[str]]:
    ed = Edits(project.root)
    skipped: list[str] = []
    min_sdk, min_ios = _min_target_sdk(), _min_ios()
    done: set = set()

    for f in findings:
        key = (f.rule_id, f.location, f.detail)
        if key in done:
            continue
        done.add(key)
        if f.rule_id == "play.debuggable":
            t = ed.get(f.location)
            if t is not None:
                new = re.sub(r'\s+android:debuggable\s*=\s*"true"', "", t)
                if new != t:
                    ed.set(f.location, new)
                    continue
            skipped.append(f"{f.rule_id}: {f.location}")
        elif f.rule_id == "play.target_sdk":
            t = ed.get(f.location)
            if t is None or f.location.endswith(".apk"):
                skipped.append(f"{f.rule_id}: {f.location} (not a text file)")
                continue

            def bump(m):
                return m.group(1) + str(max(int(m.group(2)), min_sdk)) if int(m.group(2)) < min_sdk else m.group(0)
            new = re.sub(r"(\btargetSdk(?:Version)?[\"']?\s*(?:=|:|\s)\s*[\"']?)(\d+)\b", bump, t)
            if new != t:
                ed.set(f.location, new)
                continue
            skipped.append(f"{f.rule_id}: {f.location} (value is defined elsewhere)")
        elif f.rule_id == "play.exported_missing":
            m = re.match(r"<(\S+) (\S+)>", f.detail)
            t = ed.get(f.location)
            if not m or t is None:
                skipped.append(f"{f.rule_id}: {f.location}")
                continue
            tag, name = m.group(1), m.group(2)
            launcher = "LAUNCHER" in f.detail
            value = "true" if launcher else "false"
            if 'android:exported="false"' in f.detail:             # existing exported="false" on a launcher
                rx = re.compile(r"(<" + re.escape(tag) + r"\b[^>]*?android:name=\"" + re.escape(name)
                                + r"\"[^>]*?android:exported=\")false(\")")
                new = rx.sub(r"\1true\2", t, count=1)
            else:
                rx = re.compile(r"(<" + re.escape(tag) + r"\b)([^>]*?android:name=\"" + re.escape(name) + r"\")")
                new = rx.sub(r'\1 android:exported="' + value + r'"\2', t, count=1)
            if new != t:
                ed.set(f.location, new)
            else:
                skipped.append(f"{f.rule_id}: {f.location} ({name})")
        elif f.rule_id == "apple.deployment_target":
            t = ed.get(f.location)
            if t is None:
                skipped.append(f"{f.rule_id}: {f.location}")
                continue
            target = float(min_ios)
            new = re.sub(r"(IPHONEOS_DEPLOYMENT_TARGET\s*=\s*\"?)([0-9.]+)",
                         lambda m: m.group(1) + min_ios if float(m.group(2)) < target else m.group(0), t)
            new = re.sub(r"(platform\s*:ios\s*,\s*['\"])([0-9.]+)(['\"])",
                         lambda m: m.group(1) + min_ios + m.group(3) if float(m.group(2)) < target else m.group(0), new)
            if new != t:
                ed.set(f.location, new)
            elif ed.orig.get(f.location) == t:           # nothing to change and nothing changed earlier
                skipped.append(f"{f.rule_id}: {f.location}")
        elif f.rule_id == "apple.usage_strings":
            m = re.search(r"has no (NS\w+)", f.detail)
            if not m:
                continue
            plists = [l for l, _ in project.plists if l not in project.synthetic_plists
                      and "/macos/" not in "/" + l.lower() and l.endswith(".plist")]
            if not plists:
                skipped.append(f"{f.rule_id}: no editable Info.plist (generated or binary) for {m.group(1)}")
                continue
            for rel in plists:
                t = ed.get(rel)
                if t is None or f"<key>{m.group(1)}</key>" in t or "</dict>" not in t:
                    continue
                i = t.rfind("</dict>")
                ins = f"\t<key>{m.group(1)}</key>\n\t<string>{TODO_STRING}</string>\n"
                ed.set(rel, t[:i] + ins + t[i:])
        elif f.rule_id.startswith(("play.", "apple.", "listing.", "both.")):
            skipped.append(f"{f.rule_id}: {f.location}")
    return ed, sorted(set(skipped))


def to_patch(ed: Edits) -> str:
    parts = []
    for rel in sorted(ed.text):
        old, new = ed.orig[rel], ed.text[rel]
        if old == new:
            continue
        lines = []
        for ln in difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}", n=3):
            lines.append(ln if ln.endswith("\n") else ln + "\n\\ No newline at end of file\n")
        parts.append("".join(lines))
    return "\n".join(p if p.endswith("\n") else p + "\n" for p in parts)
