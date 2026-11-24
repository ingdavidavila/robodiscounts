"""Draft Google Data safety and Apple privacy label answers from project evidence.

The draft lists data types the app *may* collect, with evidence. Only the developer
can answer the rest (purposes, sharing, retention), so those come out as questions.
Everything here is a starting point to check, never a submission-ready answer.
"""
from __future__ import annotations

import json
from pathlib import Path

from .checks import ANDROID, TOOLS, _manifest_roots
from .discover import Project

DATA = json.loads((Path(__file__).parent / "privacy_data.json").read_text())

GOOGLE_PURPOSES = ["App functionality", "Analytics", "Developer communications",
                   "Advertising or marketing", "Fraud prevention, security, and compliance",
                   "Personalization", "Account management"]


def build_draft(project: Project) -> dict:
    entries: dict[str, dict] = {}
    tracking: list[str] = []
    notes: list[str] = []

    def add(key, kind, what, where, transmits, purposes=(), hint=""):
        e = entries.setdefault(key, {"evidence": [], "purposes": set(), "hints": set(), "transmits": False})
        e["evidence"].append({"kind": kind, "what": what, "where": where})
        e["transmits"] |= transmits
        e["purposes"].update(purposes)
        if hint:
            e["hints"].add(hint)

    for sig in DATA["signals"]:
        for where in project.find_signals(sig["pattern"]):
            for key in sig["data"]:
                add(key, sig["kind"], sig["name"], where, sig["transmits"], sig["purposes"], sig["hint"])
            if sig["tracking"]:
                tracking.append(sig["name"])
            break  # one location per signal is enough evidence for the draft

    for m, root in _manifest_roots(project):
        for el in list(root.iter("uses-permission")) + list(root.iter("uses-permission-sdk-23")):
            if el.get(TOOLS + "node") == "remove":
                continue
            short = el.get(ANDROID + "name", "").rsplit(".", 1)[-1]
            for key in DATA["permissions"]["android_permissions"].get(short, []):
                add(key, "permission", f"Android permission {short}", str(m.relative_to(project.root)), False)

    for label, d in project.plists:
        for k, keys in DATA["permissions"]["ios_plist_keys"].items():
            if k in d:
                for key in keys:
                    add(key, "plist", f"Info.plist {k}", label, False)
        if DATA["permissions"]["ios_tracking_key"] in d:
            tracking.append("NSUserTrackingUsageDescription present")

    if project.find_signal(DATA["network_pattern"]):
        notes.append("A network library is present. Anything you send to your own backend (accounts, "
                     "uploads, messages) also counts as collected; add those types by hand.")

    rows = []
    for key, e in entries.items():
        t = DATA["data_types"][key]
        kinds = {x["kind"] for x in e["evidence"]}
        if e["transmits"]:
            strength = "likely collected (SDK sends data off-device)"
        elif len(kinds) > 1:
            strength = "possible (permission and API both present; collected only if it leaves the device)"
        else:
            strength = "possible (capability only; collected only if it leaves the device)"
        rows.append({"key": key, **t, "strength": strength, "evidence": e["evidence"],
                     "purposes_hint": sorted(e["purposes"]), "hints": sorted(e["hints"])})
    rows.sort(key=lambda r: (not r["strength"].startswith("likely"), r["google_category"] or "~", r["key"]))
    return {"verified": DATA["verified"], "mapping_note": DATA["note"], "rows": rows,
            "tracking_signals": sorted(set(tracking)), "notes": notes}


def to_markdown(draft: dict) -> str:
    L = ["# Privacy label draft", "",
         "> **Draft only.** Built from code and manifest evidence. The mappings are unverified "
         "(see below) and the store forms ask things only you can answer. Review every row.", ""]
    L += [f"Mapping status: {'verified' if draft['verified'] else 'NOT verified against current store docs/vendor guides'}. "
          + draft["mapping_note"], ""]
    if not draft["rows"]:
        L.append("No data-collection evidence found. That does not mean none exists: check anything "
                 "you send to your own servers.")
    else:
        L += ["## Detected data types", "",
              "| Data | Google Data safety | Apple privacy label | Status | Evidence |", "|---|---|---|---|---|"]
        for r in draft["rows"]:
            g = f"{r['google_category']} › {r['google_type']}" if r["google_category"] else "(no direct equivalent)"
            ev = "; ".join(f"{e['what']} ({e['where']})" for e in r["evidence"][:3])
            L.append(f"| {r['key']} | {g} | {r['apple_category']} › {r['apple_type']} | {r['strength']} | {ev} |")
        hints = [(r["key"], h) for r in draft["rows"] for h in r["hints"]]
        if hints:
            L += ["", "### SDK notes", ""] + [f"- **{k}**: {h}" for k, h in hints]
    if draft["tracking_signals"]:
        L += ["", "## Tracking (Apple)", "",
              "These suggest data may be used for tracking, which means declaring it, showing the App "
              "Tracking Transparency prompt, and setting `NSUserTrackingUsageDescription`: "
              + ", ".join(draft["tracking_signals"]) + "."]
    for n in draft["notes"]:
        L += ["", f"**Note:** {n}"]
    L += ["", "## What only you can answer", "", "### Google Play Data safety (per data type)", ""]
    L += ["- Is it **collected** (leaves the device), **shared** with third parties, or both? "
          "(Google excludes data processed only on-device, and has rules about service providers.)",
          "- Is collection **required** or **optional** for users?",
          "- Purposes: " + ", ".join(GOOGLE_PURPOSES) + ".",
          "- Is all data **encrypted in transit**?",
          "- Can users **request deletion**? (Also requires a web deletion link if you have accounts.)",
          "- Privacy policy URL, and whether the app targets children (Families policy)."]
    L += ["", "### Apple App Privacy (per data type)", "",
          "- Is it **linked to the user's identity**?",
          "- Is it **used for tracking** (combined with other companies' data for ads, or shared with data brokers)?",
          "- Purposes: Third-Party Advertising, Developer's Advertising or Marketing, Analytics, "
          "Product Personalization, App Functionality, Other.",
          "- Third-party SDK data counts as yours: check each SDK's privacy manifest and disclosure guide.",
          "- Privacy policy URL."]
    return "\n".join(L)
