"""Generic check types. Rules (JSON) pick a type and supply parameters.

Each check takes (project, params) and returns a list of (location, message).
"""
from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET

from .discover import Project

ANDROID = "{http://schemas.android.com/apk/res/android}"
TOOLS = "{http://schemas.android.com/tools}"
PAGE_16K = 0x4000


def _manifest_roots(p: Project):
    """(label, root element) for every readable manifest: source files and decoded APK manifests."""
    for m in p.android_manifests:
        try:
            yield m.relative_to(p.root).as_posix(), ET.parse(m).getroot()
        except ET.ParseError:
            continue
    yield from p.archive_manifests


def android_permission(p: Project, a: dict):
    bad = set(a["permissions"])
    out = []
    for m, root in _manifest_roots(p):
        for el in list(root.iter("uses-permission")) + list(root.iter("uses-permission-sdk-23")):
            if el.get(TOOLS + "node") == "remove":
                continue
            name = el.get(ANDROID + "name", "")
            if name.rsplit(".", 1)[-1] in bad:
                out.append((m, name))
    out += [(where, short) for where, short in p.extra_permissions if short in bad]
    return out


def android_attr(p: Project, a: dict):
    out = []
    for m, root in _manifest_roots(p):
        app = root.find("application")
        if app is not None and app.get(ANDROID + a["attr"]) == a["bad_value"]:
            out.append((m, f'android:{a["attr"]}="{a["bad_value"]}"'))
    return out


_TARGET_RX = re.compile(r"\btargetSdk(?:Version)?[\"']?\s*(?:=|:|\s)\s*[\"']?(\d+)\b")
# newer AGP DSL:  targetSdk { version = release(36) }  or  release(SOME_CONSTANT)
_TARGET_BLOCK_RX = re.compile(r"\btargetSdk\s*\{\s*version\s*=\s*(?:release\(\s*)?(\w+)\s*\)?")


def _resolve_constant(p: Project, name: str):
    rx = re.compile(r"\b" + re.escape(name) + r"\s*[=:]\s*(\d+)\b")
    for _, text in p.sdk_sources:
        m = rx.search(text)
        if m:
            return int(m.group(1))
    return None


def _target_sdk_values(p: Project):
    """(location, value) for targetSdk assignments in app modules and shared build config."""
    vals = []
    for rel, text in p.sdk_sources:
        name = rel.replace("\\", "/").rsplit("/", 1)[-1]
        if name in ("build.gradle", "build.gradle.kts") and (
                "com.android.library" in text or "android-library" in text):
            continue  # library module, not the app
        vals += [(rel, int(m.group(1))) for m in _TARGET_RX.finditer(text)]
        for m in _TARGET_BLOCK_RX.finditer(text):
            tok = m.group(1)
            v = int(tok) if tok.isdigit() else _resolve_constant(p, tok)
            if v is not None:
                vals.append((rel, v))
    archive = {l for l, _ in p.archive_manifests}
    has_base = {l.split("!")[0] for l in archive if _module_of(l) == "base"}
    for mf, root in _manifest_roots(p):
        sdk = root.find("uses-sdk")
        v = sdk.get(ANDROID + "targetSdkVersion") if sdk is not None else None
        if mf in archive:
            # Built artifacts: Android's rule is that a missing targetSdkVersion equals minSdkVersion (default 1).
            # In a bundle only the base module is compared (an assumption: the app's target is the base module's).
            if _module_of(mf) not in (None, "base") and mf.split("!")[0] in has_base:
                continue
            mn = sdk.get(ANDROID + "minSdkVersion") if sdk is not None else None
            eff = v if v and v.isdigit() else (mn if mn and mn.isdigit() else "1")
            vals.append((mf, int(eff)))
        elif v and v.isdigit():
            vals.append((mf, int(v)))
    return vals


def _module_of(label: str):
    """'app.aab!base/manifest/AndroidManifest.xml' -> 'base'; None for APKs and source manifests."""
    if ".aab!" not in label:
        return None
    return label.split("!", 1)[1].split("/", 1)[0]


def android_target_sdk(p: Project, a: dict):
    return [(loc, f"targetSdk {v} < {a['min_target_sdk']}")
            for loc, v in _target_sdk_values(p) if v < a["min_target_sdk"]]


def android_target_sdk_unknown(p: Project, a: dict):
    if _target_sdk_values(p):
        return []
    if not (p.gradle_files or p.android_manifests or p.android_hint or p.archive_manifests):
        return []
    return [("(project)", "no numeric targetSdk found; it may be inherited from Flutter, React Native, "
                          "Expo, a version catalog, Unity's 'Automatic (highest installed)' setting, "
                          ".NET MAUI's or Godot's default API level")]


def plist_value(p: Project, a: dict):
    out = []
    for label, d in p.plists:
        cur = d
        for k in a["path"]:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur == a["bad_value"]:
            out.append((label, "/".join(a["path"]) + f" = {a['bad_value']}"))
    return out


def plist_key_missing(p: Project, a: dict):
    out = []
    for label, d in p.plists:
        missing = [k for k in a["keys"] if k not in d]
        if missing:
            out.append((label, "missing " + ", ".join(missing)))
    return out


def privacy_manifest_missing(p: Project, a: dict):
    if p.has_privacy_manifest:
        return []
    if p.plists and all(label in p.synthetic_plists for label, _ in p.plists):
        return [("(project)", "no PrivacyInfo.xcprivacy or privacyManifests config found; generated projects "
                              "may add one at build time, so check the generated ios/ folder", "advisory")]
    return [("(project)", "no PrivacyInfo.xcprivacy found")]


def signal_requires_plist_key(p: Project, a: dict):
    if not p.plists:
        return []
    only_inferred = all(label in p.synthetic_plists for label, _ in p.plists)
    out = []
    for s in a["signals"]:
        hit = p.find_signal(s["pattern"])
        keys = s.get("keys") or [s["key"]]
        if hit and not any(k in d for _, d in p.plists for k in keys):
            detail = f"{s['what']} detected but Info.plist has no " + " or ".join(keys)
            if only_inferred:
                note = next(iter(p.synthetic_plists.values()))
                out.append((hit, detail + f" (Info.plist is inferred from config: {note}; confirm in the "
                                          "generated project)", "likely"))
            else:
                out.append((hit, detail))
    return out


def signal_without(p: Project, a: dict):
    hit = p.find_signal(a["signal"])
    if hit and not p.find_signal(a["unless"]):
        return [(hit, a["what"])]
    return []


def apk_without_aab(p: Project, a: dict):
    kinds = {x.suffix for x in p.artifacts}
    return [(x.name, "APK supplied, no AAB") for x in p.artifacts
            if x.suffix == ".apk" and ".aab" not in kinds]


_ELF_MACHINES = {183: "arm64-v8a", 62: "x86_64"}


def elf_alignment(p: Project, a: dict):
    bad = []
    for label, head in p.native_libs:
        if head[:4] != b"\x7fELF" or len(head) < 64 or head[4] != 2 or head[5] != 1:
            continue  # only 64-bit little-endian ELF
        e_machine = struct.unpack_from("<H", head, 18)[0]
        if e_machine not in _ELF_MACHINES:
            continue
        phoff = struct.unpack_from("<Q", head, 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", head, 54)
        for i in range(phnum):
            off = phoff + i * phentsize
            if off + 56 > len(head):
                break
            p_type = struct.unpack_from("<I", head, off)[0]
            p_align = struct.unpack_from("<Q", head, off + 48)[0]
            if p_type == 1 and p_align < PAGE_16K:
                bad.append((label, f"{_ELF_MACHINES[e_machine]} LOAD alignment 0x{p_align:x} < 0x4000"))
                break
    return bad


CHECKS = {f.__name__: f for f in (
    android_permission, android_attr, android_target_sdk, android_target_sdk_unknown, plist_value, plist_key_missing,
    privacy_manifest_missing, signal_requires_plist_key, signal_without, apk_without_aab,
    elf_alignment)}

