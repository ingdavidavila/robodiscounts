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
from .rating import rating_hints

DATA = json.loads((Path(__file__).parent / "privacy_data.json").read_text(encoding="utf-8"))

GOOGLE_PURPOSES = ["App functionality", "Analytics", "Developer communications",
                   "Advertising or marketing", "Fraud prevention, security, and compliance",
                   "Personalization", "Account management"]


_NOT_EVIDENCE_SUFFIXES = {".unity", ".asset", ".prefab", ".mat", ".anim", ".controller", ".meta", ".svg", ".arb",
                          ".strings", ".po", ".csv", ".tsv", ".ttf", ".otf", ".lottie", ".txt",
                          ".hlsl", ".glsl", ".shader", ".cginc", ".compute", ".gdshader"}
_NOT_EVIDENCE_NAMES = {".gitignore", ".gitattributes", ".dockerignore", ".npmignore", ".editorconfig", "codeowners"}
_CONFIG_JSON = {"package.json", "app.json", "manifest.json", "google-services.json", "composer.json"}


def _evidence_ok(name: str) -> bool:
    """SDK evidence must come from code, manifests or dependency files, not art, scenes or translations."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in _NOT_EVIDENCE_NAMES:
        return False
    if base in _CONFIG_JSON:
        return True
    suffix = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    if suffix == ".json":
        return False
    return suffix not in _NOT_EVIDENCE_SUFFIXES


def _items(sig):
    """Normalize a signal's data list: strings or {"key", "only", "usage_dependent"}."""
    for it in sig["data"]:
        yield (it, None, False) if isinstance(it, str) else (it["key"], it.get("only"), bool(it.get("usage_dependent")))


def build_draft(project: Project) -> dict:
    entries: dict[str, dict] = {}
    tracking: list[str] = []
    notes: list[str] = []
    sdk_notes: list[dict] = []

    def add(key, kind, what, where, transmits, purposes=(), hint="", only=None, usage_dep=False, verified=""):
        e = entries.setdefault(key, {"evidence": [], "purposes": set(), "hints": set(), "certain": False,
                                     "sdk_dep": False, "stores": set()})
        e["evidence"].append({"kind": kind, "what": what, "where": where, "verified": verified,
                              "usage_dependent": usage_dep, "only": only})
        if kind == "sdk":
            if transmits and not usage_dep:
                e["certain"] = True
            else:
                e["sdk_dep"] = True
        e["stores"].add(only or "both")
        e["purposes"].update(purposes)
        if hint:
            e["hints"].add(hint)

    for sig in DATA["signals"]:
        hits = [h for h in project.find_signals(sig["pattern"], limit=400)
                if sig["kind"] != "sdk" or _evidence_ok(h)]
        if not hits:
            continue
        dep_files = DATA["dependency_files"]
        # prefer a dependency declaration as the evidence location over an arbitrary source file
        where = min(hits, key=lambda h: (h.replace("\\", "/").rsplit("/", 1)[-1].lower() not in dep_files, 0))
        off = project.find_signal(sig["disabled_pattern"]) if sig.get("disabled_pattern") else None
        what = sig["name"] + (f" (collection disabled by default in {off})" if off else "")
        hint = sig["hint"] + (f" Collection looks disabled by default in {off}; it still counts if you turn it "
                              "on later, for example after consent." if off else "")
        for key, only, usage_dep in _items(sig):
            add(key, sig["kind"], what, where, sig["transmits"], sig["purposes"], hint,
                only, usage_dep or bool(off), sig.get("verified", ""))
        if sig["tracking"] and not off:
            tracking.append(sig["name"])
        if sig["kind"] == "sdk":
            sdk_notes.append({"name": sig["name"], "where": where, "hint": hint,
                              "verified": sig.get("verified", ""), "sources": sig.get("sources", [])})

    for m, root in _manifest_roots(project):
        for el in list(root.iter("uses-permission")) + list(root.iter("uses-permission-sdk-23")):
            if el.get(TOOLS + "node") == "remove":
                continue
            short = el.get(ANDROID + "name", "").rsplit(".", 1)[-1]
            for key in DATA["permissions"]["android_permissions"].get(short, []):
                add(key, "permission", f"Android permission {short}", m, False,
                    only="google")

    for where, short in project.extra_permissions:
        for key in DATA["permissions"]["android_permissions"].get(short, []):
            add(key, "permission", f"Android permission {short} (config)", where, False, only="google")

    for label, d in project.plists:
        for k, keys in DATA["permissions"]["ios_plist_keys"].items():
            if k in d:
                for key in keys:
                    add(key, "plist", f"Info.plist {k}", label, False, only="apple")
        if DATA["permissions"]["ios_tracking_key"] in d:
            tracking.append("NSUserTrackingUsageDescription present")

    if project.find_signal(DATA["network_pattern"]):
        notes.append("A network library is present. Anything you send to your own backend (accounts, "
                     "uploads, messages) also counts as collected; add those types by hand.")

    rows = []
    for key, e in entries.items():
        t = DATA["data_types"][key]
        kinds = {x["kind"] for x in e["evidence"]}
        if e["certain"]:
            strength = "likely collected (SDK sends data off-device)"
        elif e["sdk_dep"]:
            strength = "possible (depends on how you use the SDK)"
        elif len(kinds) > 1:
            strength = "possible (permission and API both present; collected only if it leaves the device)"
        else:
            strength = "possible (capability only; collected only if it leaves the device)"
        stores = "both" if "both" in e["stores"] or len(e["stores"]) > 1 else next(iter(e["stores"]))
        rows.append({"key": key, **t, "strength": strength, "stores": stores, "evidence": e["evidence"],
                     "purposes_hint": sorted(e["purposes"]), "hints": sorted(e["hints"])})
    rows.sort(key=lambda r: (not r["strength"].startswith("likely"), r["google_category"] or "~", r["key"]))
    return {"verified": DATA["verified"], "mapping_note": DATA["note"], "rows": rows, "sdk_notes": sdk_notes,
            "tracking_signals": sorted(set(tracking)), "notes": notes, "rating": rating_hints(project)}


def to_markdown(draft: dict) -> str:
    L = ["# Privacy label draft", "",
         "> **Draft only.** Built from code and manifest evidence. SDK mappings are marked verified or unverified "
         "below, and the store forms ask things only you can answer. Review every row.", ""]
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
            ev = "; ".join(f"{e['what']} ({e['where']})" + ("" if e["kind"] != "sdk" or e["verified"]
                                                               else " [mapping unverified]")
                            for e in r["evidence"][:3])
            status = r["strength"] + (f" ({r['stores'].capitalize()} only)" if r["stores"] != "both" else "")
            L.append(f"| {r['key']} | {g} | {r['apple_category']} › {r['apple_type']} | {status} | {ev} |")
        if draft["sdk_notes"]:
            L += ["", "### SDK notes", ""]
            for n in draft["sdk_notes"]:
                v = f"mapping verified {n['verified']}" if n["verified"] else "mapping NOT verified"
                src = (" Sources: " + ", ".join(n["sources"])) if n["sources"] else ""
                L.append(f"- **{n['name']}** ({v}): {n['hint']}{src}".rstrip())
    if draft["tracking_signals"]:
        L += ["", "## Tracking (Apple)", "",
              "These suggest data may be used for tracking, which means declaring it, showing the App "
              "Tracking Transparency prompt, and setting `NSUserTrackingUsageDescription`: "
              + ", ".join(draft["tracking_signals"]) + "."]
    for n in draft["notes"]:
        L += ["", f"**Note:** {n}"]
    if draft.get("rating"):
        L += ["", "## Age and content rating hints", "",
              "Apple's age rating asks about these capabilities (verified against Apple's age ratings page); Google's "
              "IARC questionnaire asks similar things (its wording was not read). The code only shows what is present, "
              "so answer from what the app really does:", ""]
        L += [f"- **{r['topic']}** (seen in {r['evidence']}): {r['ask']}" for r in draft["rating"]]
        L += ["", "Apple also required updated age rating answers in App Store Connect (new system effective "
              "31 January 2026)."]
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
