"""Checks added for the requirement areas beyond the first rule set.

Every threshold comes from a rule's parameters (rules/extra.json), each with its source and date.
Each check takes (project, params) and returns a list of (location, message[, severity]).
"""
from __future__ import annotations

import json
import re

from .checks import ANDROID, TOOLS, _manifest_roots, _target_sdk_values
from .discover import Project
from .media import image_size

COMPONENTS = ("activity", "activity-alias", "service", "receiver")


# --- Android ----------------------------------------------------------------------------------
def _known_target_below(p: Project, minimum: int) -> bool:
    vals = [v for _, v in _target_sdk_values(p)]
    return bool(vals) and all(v < minimum for v in vals)


def android_exported_missing(p: Project, a: dict):
    """Android 12+: components with an intent-filter must declare android:exported explicitly."""
    if _known_target_below(p, 31):
        return []
    out = []
    for label, root in _manifest_roots(p):
        app = root.find("application")
        if app is None:
            continue
        for comp in app:
            if comp.tag not in COMPONENTS or comp.get(TOOLS + "node") == "remove":
                continue
            name = comp.get(ANDROID + "name", "?")
            filters = comp.findall("intent-filter")
            exported = comp.get(ANDROID + "exported")
            launcher = any(c.get(ANDROID + "name") == "android.intent.category.LAUNCHER"
                           for f in filters for c in f.findall("category"))
            if filters and exported is None:
                out.append((label, f"<{comp.tag} {name}> has an intent-filter but no android:exported"
                                   + (" (it is a LAUNCHER activity)" if launcher else "")))
            if launcher and exported == "false":
                out.append((label, f"<{comp.tag} {name}> is a LAUNCHER activity but android:exported=\"false\""))
    return out


_FGS_SIGNAL = (r"startForeground|startForegroundService|ServiceCompat\.startForeground|ForegroundService|"
               r"flutter_foreground_task|foreground-service|react-native-foreground-service|notifee")
_LIBRARY_SERVICE = re.compile(r"^(androidx\.|android\.|com\.google\.(android|firebase)\.|com\.facebook\.)")


def android_fgs_type_missing(p: Project, a: dict):
    """Android 14: foreground services must declare a type. Reported only when the code starts foreground
    services, and only for the app's own services that aren't system-bound or library-provided."""
    if _known_target_below(p, 34) or not p.find_signal(_FGS_SIGNAL):
        return []
    out = []
    for label, root in _manifest_roots(p):
        perms = {e.get(ANDROID + "name", "").rsplit(".", 1)[-1] for e in root.iter("uses-permission")
                 if e.get(TOOLS + "node") != "remove"}
        if "FOREGROUND_SERVICE" not in perms:
            continue
        app = root.find("application")
        missing = []
        for sv in (app.findall("service") if app is not None else []):
            name = sv.get(ANDROID + "name", "?")
            if (sv.get(ANDROID + "foregroundServiceType") is not None or sv.get(TOOLS + "node") == "remove"
                    or sv.get(ANDROID + "permission") is not None or sv.get(ANDROID + "enabled") == "false"
                    or _LIBRARY_SERVICE.match(name)):
                continue
            missing.append(name)
        if missing:
            out.append((label, "FOREGROUND_SERVICE is declared and the code starts foreground services; "
                               "services without foregroundServiceType: " + ", ".join(missing[:6])
                               + (" ..." if len(missing) > 6 else "")))
    return out


def _balanced(text: str, open_idx: int) -> str:
    depth, i = 0, open_idx
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
        i += 1
    return text[open_idx:]


_SIGNING_REF = re.compile(
    r"signingConfig\s*(?:=\s*)?(signingConfigs(?:\.getByName\(\s*[\"'][^\"']*[\"']\s*\)"
    r"|\.named\(\s*[\"'][^\"']*[\"']\s*\)|\[\s*[\"'][^\"']*[\"']\s*\]|\.\w+))")


def android_release_debug_signing(p: Project, a: dict):
    """Flag a release build type whose only signing config is the debug one. A debug fallback next to a real
    release config (for example when no keystore is present on a dev machine) is not flagged."""
    out = []
    for g in p.gradle_files:
        text = g.read_text(encoding="utf-8", errors="ignore")
        for bt in re.finditer(r"\bbuildTypes\s*\{", text):
            block = _balanced(text, bt.end() - 1)
            for rel in re.finditer(r"\b(?:release|getByName\(\s*[\"']release[\"']\s*\))\s*\{", block):
                refs = [m.group(1) for m in _SIGNING_REF.finditer(_balanced(block, rel.end() - 1))]
                if refs and all(re.search(r"debug", r) for r in refs):
                    out.append((g.relative_to(p.root).as_posix(), "release build type is signed only with the debug key"))
    return out


# --- iOS --------------------------------------------------------------------------------------
def _is_ios_plist(label: str, d: dict) -> bool:
    return "LSMinimumSystemVersion" not in d and "/macos/" not in "/" + label.lower().replace("\\", "/")


def _real_ios_plists(p: Project):
    return [(l, d) for l, d in p.plists if l not in p.synthetic_plists and _is_ios_plist(l, d)]


def ios_app_icon(p: Project, a: dict):
    want = a["size"]
    if not p.has_ios_project and not p.appicon_sets:
        return []
    if p.has_icon_composer:
        return []
    out = []
    ios_sets = 0
    for cj in p.appicon_sets:
        try:
            data = json.loads(cj.read_text(encoding="utf-8", errors="ignore"))
        except ValueError:
            continue
        images = data.get("images", [])
        is_ios = any(i.get("idiom") in ("iphone", "ipad", "ios-marketing") or
                     (i.get("idiom") == "universal" and i.get("platform") == "ios") for i in images)
        if not is_ios:
            continue
        ios_sets += 1
        label = cj.relative_to(p.root).as_posix()
        big = [i for i in images if i.get("size") == f"{want}x{want}"]
        if not big:
            out.append((label, f"no {want}x{want} entry in the app icon set"))
            continue
        fn = big[0].get("filename")
        if not fn:
            out.append((label, f"the {want}x{want} icon slot has no image file"))
            continue
        path = cj.parent / fn
        size = image_size(path) if path.exists() else None
        if size is None:
            out.append((label, f"{fn} is missing or not a readable PNG/JPEG"))
        elif size != (want, want):
            out.append((path.relative_to(p.root).as_posix(), f"icon is {size[0]}x{size[1]}, expected {want}x{want}"))
    if not ios_sets and p.has_ios_project and p.plists and not any(l in p.synthetic_plists for l, _ in p.plists):
        out.append(("(project)", "no iOS app icon set (AppIcon.appiconset) or Icon Composer .icon bundle found"))
    return out


def ios_launch_screen(p: Project, a: dict):
    out = []
    for label, d in _real_ios_plists(p):
        if not any(k.startswith(("UILaunchScreen", "UILaunchStoryboard")) for k in d):
            out.append((label, "no UILaunchScreen or UILaunchStoryboardName"))
    return out


def _versions(text: str, rx: str):
    return [m.group(1) for m in re.finditer(rx, text)]


def _as_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:2] or [0])


def ios_deployment_target(p: Project, a: dict):
    minimum = tuple(a["min_version"])
    sources = []
    for f in p.config_files:
        if f.name == "project.pbxproj" or f.suffix == ".xcconfig":
            sources.append((f.relative_to(p.root).as_posix(), f.read_text(encoding="utf-8", errors="ignore"),
                            r"IPHONEOS_DEPLOYMENT_TARGET\s*=\s*\"?([0-9.]+)"))
        elif f.name in ("app.json",) or re.fullmatch(r"app\.config\.\w+", f.name):
            sources.append((f.relative_to(p.root).as_posix(), f.read_text(encoding="utf-8", errors="ignore"),
                            r"[\"']?deploymentTarget[\"']?\s*:\s*[\"']([0-9.]+)"))
    for name, text, _lock in p.texts:
        low = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if low == "podfile":
            text = re.sub(r"(?m)^\s*#.*$", "", text)
            sources.append((name, text, r"platform\s*:ios\s*,\s*[\"']([0-9.]+)"))
        elif low == "package.swift":
            text = re.sub(r"(?m)//.*$", "", text)
            sources.append((name, text, r"\.iOS\(\s*\.v(\d+)\s*\)"))
    out, seen = [], set()
    for label, text, rx in sources:
        for v in _versions(text, rx):
            if _as_tuple(v) < minimum and (label, v) not in seen:
                seen.add((label, v))
                out.append((label, f"deployment target {v} is below iOS {'.'.join(map(str, minimum))}"))
    return out


_XCODE_RX = [r"xcode-version\s*:\s*[\"']?(\d+)", r"Xcode[_ -](\d+)(?:\.\d+)*(?:\.app)?", r"\bxcode\s*:\s*[\"']?(\d+)"]


def ios_xcode_version(p: Project, a: dict):
    minimum = a["min_major"]
    out = []
    for name, text, _lock in p.texts:
        low = name.replace("\\", "/").lower()
        is_ci = (".github/workflows/" in low or low.endswith((".gitlab-ci.yml", "bitrise.yml", "codemagic.yaml",
                                                              "codemagic.yml", ".xcode-version", "fastfile"))
                 or ".circleci/" in low)
        if not is_ci:
            continue
        rxs = [r"^\s*(\d+)(?:\.\d+)*\s*$"] if low.endswith(".xcode-version") else _XCODE_RX
        for rx in rxs:
            for m in re.finditer(rx, text, re.M):
                if int(m.group(1)) < minimum:
                    out.append((name, f"CI builds with Xcode {m.group(1)}; uploads need Xcode {minimum} or later"))
                    break
    return out


def ios_push_entitlement(p: Project, a: dict):
    plists = _real_ios_plists(p)
    if not plists or not p.has_ios_project:
        return []
    hit = p.find_signal(a["signal"])
    if not hit:
        return []
    if any("aps-environment" in d for _, d in p.entitlements):
        return []
    where = "no .entitlements file" if not p.entitlements else "no aps-environment in the entitlements"
    return [(hit, f"push notification code found but {where}")]


def ios_background_modes(p: Project, a: dict):
    out = []
    for label, d in _real_ios_plists(p):
        modes = d.get("UIBackgroundModes")
        if not isinstance(modes, list):
            continue
        for m in modes:
            sig = a["signals"].get(m)
            if sig and not p.find_signal(sig):
                out.append((label, f"UIBackgroundModes has '{m}' but no matching code was found"))
        if "location" in modes and not any(k.startswith("NSLocation") for k in d):
            out.append((label, "UIBackgroundModes has 'location' but no NSLocation...UsageDescription"))
    return out


# --- Both stores ------------------------------------------------------------------------------
_DEP_FILES = {"package.json", "pubspec.yaml", "podfile", "package.swift", "build.gradle", "build.gradle.kts",
              "libs.versions.toml", "cargo.toml", "requirements.txt", "config.xml"}


def payments_without_iap(p: Project, a: dict):
    """A payment SDK is judged by dependency declarations only: the word 'stripe' also appears in art and text."""
    rx = re.compile(a["payment"])
    hit = next((n for n, t, lock in p.texts
                if not lock and n.replace("\\", "/").rsplit("/", 1)[-1].lower() in _DEP_FILES and rx.search(t)), None)
    if not hit or p.find_signal(a["iap"]):
        return []
    return [(hit, "a payment SDK is declared and no in-app purchase library was found")]


def _is_android_listing(path) -> bool:
    return any(x.lower() == "android" for x in path.parts)


def listing_limits(p: Project, a: dict):
    limits = a["limits"]          # file name -> {"max": n, "unit": "chars"|"bytes", "min": n?}
    android = a["android"]
    out = []
    for f in p.listing_files:
        if _is_android_listing(f.relative_to(p.root)) != android or f.name not in limits:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore").rstrip("\n")
        rule = limits[f.name]
        n = len(text.encode("utf-8")) if rule.get("unit") == "bytes" else len(text)
        if n > rule["max"]:
            out.append((f.relative_to(p.root).as_posix(), f"{n} {rule.get('unit', 'chars')}, limit {rule['max']}"))
        if rule.get("min") and 0 < n < rule["min"]:
            out.append((f.relative_to(p.root).as_posix(), f"{n} chars, minimum {rule['min']}"))
    return out


def listing_screenshots(p: Project, a: dict):
    out = []
    if not a["android"]:
        ok = {tuple(s) for s in a["sizes"]}
        groups: dict = {}
        for f in p.screenshots:
            rel = f.relative_to(p.root)
            if _is_android_listing(rel) or any("phonescreenshots" in x.lower() for x in rel.parts):
                continue
            groups.setdefault(f.parent, []).append(f)
            size = image_size(f)
            if size and size not in ok:
                out.append((str(rel), f"{size[0]}x{size[1]} is not an accepted App Store screenshot size"))
        for d, files in groups.items():
            if len(files) > a["max"]:
                out.append((d.relative_to(p.root).as_posix(), f"{len(files)} screenshots, at most {a['max']} per device size"))
        return out
    groups = {}
    for f in p.screenshots:
        rel = f.relative_to(p.root)
        if _is_android_listing(rel) and "phonescreenshots" in str(rel).lower():
            groups.setdefault(f.parent, []).append(f)
    for d, files in groups.items():
        if not a["min"] <= len(files) <= a["max"]:
            out.append((d.relative_to(p.root).as_posix(), f"{len(files)} phone screenshots, Play wants {a['min']} to {a['max']}"))
    return out


def privacy_policy(p: Project, a: dict):
    urls = [f for f in p.listing_files if f.name == "privacy_url.txt"]
    out = []
    for f in urls:
        v = f.read_text(encoding="utf-8", errors="ignore").strip()
        if v and not v.lower().startswith("https://"):
            out.append((f.relative_to(p.root).as_posix(), f"privacy policy URL is not https: {v[:60]}"))
    if urls or p.find_signal(a["signal"]):
        return out
    from . import privacy
    if any(r["strength"].startswith("likely") for r in privacy.build_draft(p)["rows"]):
        out.append(("(project)", "SDK data collection was detected but no privacy policy link or URL was found "
                                 "in app code, config or store metadata"))
    return out


def ugc_without_moderation(p: Project, a: dict):
    hit = p.find_signal(a["ugc"])
    if not hit or p.find_signal(a["moderation"]):
        return []
    return [(hit, "user-generated content features found but no report/block moderation code was found")]


CHECKS_EXTRA = {f.__name__: f for f in (
    android_exported_missing, android_fgs_type_missing, android_release_debug_signing, ios_app_icon,
    ios_launch_screen, ios_deployment_target, ios_xcode_version, ios_push_entitlement, ios_background_modes,
    payments_without_iap, listing_limits, listing_screenshots, privacy_policy, ugc_without_moderation)}
