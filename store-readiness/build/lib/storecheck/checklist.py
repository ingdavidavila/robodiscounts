"""The manual checklist: what storecheck cannot decide, so that nothing is skipped silently.

Built from the requirements catalog (requirements.json), which is anchored to the stores' own structure (every
numbered section of Apple's App Review Guidelines, Google Play Policy Center topics, technical requirements).

  needs_human    requirements that cannot be decided from the package: they need a person, the store console or a
                 running app (each with the reason).
  not_checked    requirements that could be checked statically but are not built yet.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

CATALOG = Path(__file__).parent / "requirements.json"


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["items"]


def _stores_for(project) -> set[str]:
    if project is None:
        return {"apple", "google"}
    s = set()
    if project.has_ios:
        s.add("apple")
    if project.has_android:
        s.add("google")
    return s or {"apple", "google"}


def _group_key(item: dict) -> str:
    """Apple guideline 2.5.4 groups under 2.5; everything else groups by its own id."""
    iid = item["id"]
    if iid.startswith("apple.guideline."):
        parts = iid.split(".")[2:]
        return "apple.guideline." + ".".join(parts[:2])
    return iid


def build_checklist(project=None) -> dict:
    stores = _stores_for(project)
    out = {"needs_human": OrderedDict(), "not_checked": OrderedDict()}
    for it in _catalog():
        if it["store"] not in stores or it["class"] not in ("not_checkable", "unmapped"):
            continue
        bucket = out["needs_human" if it["class"] == "not_checkable" else "not_checked"]
        g = bucket.setdefault((_group_key(it), it["store"], it.get("reason", "")),
                              {"store": it["store"], "reason": it.get("reason", ""), "title": it["title"],
                               "source": it["source"], "ids": []})
        g["ids"].append(it["id"])
    groups = {k: list(v.values()) for k, v in out.items()}
    return {"stores": sorted(stores), "needs_human": groups["needs_human"], "not_checked": groups["not_checked"],
            "ids": sorted(i for v in groups.values() for g in v for i in g["ids"])}


def checklist_ids(project=None) -> set[str]:
    return set(build_checklist(project)["ids"])


def _short(title: str, n: int = 64) -> str:
    if len(title) <= n:
        return title
    return title[:n].rsplit(" ", 1)[0] + " ..."


def to_markdown(cl: dict) -> str:
    def label(g):
        short = [i.rsplit(".", 1)[-1] if i.startswith("apple.guideline.") else None for i in g["ids"]]
        nums = [i.replace("apple.guideline.", "") for i in g["ids"] if i.startswith("apple.guideline.")]
        return (f"Apple {', '.join(nums[:6])}{' ...' if len(nums) > 6 else ''}" if nums else g["ids"][0]) if short else g["ids"][0]
    L = ["# Manual checklist", "",
         "What storecheck cannot decide or does not check yet. Passing the automated checks does not cover these.", "",
         f"Stores in scope: {', '.join(cl['stores'])}.", ""]
    L += [f"## Needs a human, the store console or a running app ({sum(len(g['ids']) for g in cl['needs_human'])})", ""]
    for g in cl["needs_human"]:
        L.append(f"- **{_short(g['title'])}** ({label(g)}): {g['reason']}. [{g['store']} source]({g['source']})")
    L += ["", f"## Not checked by storecheck yet ({sum(len(g['ids']) for g in cl['not_checked'])})", "",
          "These could be checked from the package; no check exists for them yet.", ""]
    for g in cl["not_checked"]:
        L.append(f"- **{_short(g['title'])}** ({label(g)}). [{g['store']} source]({g['source']})")
    return "\n".join(L)
