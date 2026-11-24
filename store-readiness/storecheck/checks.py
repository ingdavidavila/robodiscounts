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
    for m in p.android_manifests:
        try:
            yield m, ET.parse(m).getroot()
        except ET.ParseError:
            continue


def android_permission(p: Project, a: dict):
    bad = set(a["permissions"])
    out = []
    for m, root in _manifest_roots(p):
        for el in list(root.iter("uses-permission")) + list(root.iter("uses-permission-sdk-23")):
            if el.get(TOOLS + "node") == "remove":
                continue
            name = el.get(ANDROID + "name", "")
            if name.rsplit(".", 1)[-1] in bad:
                out.append((str(m.relative_to(p.root)), name))
    return out


def android_attr(p: Project, a: dict):
    out = []
    for m, root in _manifest_roots(p):
        app = root.find("application")
        if app is not None and app.get(ANDROID + a["attr"]) == a["bad_value"]:
            out.append((str(m.relative_to(p.root)), f'android:{a["attr"]}="{a["bad_value"]}"'))
    return out


_TARGET_RX = re.compile(r"targetSdk(?:Version)?\s*[=( ]\s*(\d+)")


def android_target_sdk(p: Project, a: dict):
    out = []
    for g in p.gradle_files:
        for m in _TARGET_RX.finditer(g.read_text(errors="ignore")):
            if int(m.group(1)) < a["min_target_sdk"]:
                out.append((str(g.relative_to(p.root)),
                            f"targetSdk {m.group(1)} < {a['min_target_sdk']}"))
    for mf, root in _manifest_roots(p):
        sdk = root.find("uses-sdk")
        v = sdk.get(ANDROID + "targetSdkVersion") if sdk is not None else None
        if v and v.isdigit() and int(v) < a["min_target_sdk"]:
            out.append((str(mf.relative_to(p.root)), f"targetSdkVersion {v} < {a['min_target_sdk']}"))
    return out


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
    return [] if p.has_privacy_manifest else [("(project)", "no PrivacyInfo.xcprivacy found")]


def signal_requires_plist_key(p: Project, a: dict):
    if not p.plists:
        return []
    out = []
    for s in a["signals"]:
        hit = p.find_signal(s["pattern"])
        if hit and not any(s["key"] in d for _, d in p.plists):
            out.append((hit, f"{s['what']} detected but Info.plist has no {s['key']}"))
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
    android_permission, android_attr, android_target_sdk, plist_value, plist_key_missing,
    privacy_manifest_missing, signal_requires_plist_key, signal_without, apk_without_aab,
    elf_alignment)}
