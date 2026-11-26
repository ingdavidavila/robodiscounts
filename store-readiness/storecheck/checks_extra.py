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


NATIVE_IOS = (".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp")


def apple_required_reason_api(p: Project, a: dict):
    """Required-reason APIs used by the app's own native code must be declared in a privacy manifest."""
    if not p.has_ios and not p.privacy_manifests:
        return []
    declared = set(p.declared_privacy_apis)
    for _, d in p.privacy_manifests:
        for e in d.get("NSPrivacyAccessedAPITypes", []) or []:
            if isinstance(e, dict) and e.get("NSPrivacyAccessedAPIType"):
                declared.add(e["NSPrivacyAccessedAPIType"])
    out = []
    for cat, rx in a["categories"].items():
        hits = p.find_in_files(rx, NATIVE_IOS, 1, skip_platform_dirs=True)
        if hits and cat not in declared:
            out.append((hits[0], f"uses a {cat.replace('NSPrivacyAccessedAPICategory', '')} required-reason API but "
                                 f"{cat} is not declared in a privacy manifest"))
    return out


def _dependency_names(p: Project) -> dict:
    """Lowercase dependency name -> file it was found in (Podfile(.lock), Package.*, pubspec.*, package.json)."""
    found: dict[str, str] = {}

    def add(n, where):
        n = n.strip().lower()
        if n:
            found.setdefault(n, where)
    for name, text, _lock in p.texts:
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base == "podfile.lock":
            for m in re.finditer(r"(?m)^\s*-\s+\"?([A-Za-z0-9_.+-]+)(?:/[\w.+-]+)?\"?\s*\(", text):
                add(m.group(1), name)
        elif base == "podfile":
            for m in re.finditer(r"pod\s+['\"]([^'\"/]+)", text):
                add(m.group(1), name)
        elif base == "package.resolved":
            for m in re.finditer(r'"identity"\s*:\s*"([^"]+)"', text):
                add(m.group(1), name)
        elif base == "package.swift":
            for m in re.finditer(r'\.package\(\s*url:\s*"[^"]*/([^/"]+?)(?:\.git)?"', text):
                add(m.group(1), name)
        elif base in ("pubspec.yaml", "pubspec.lock"):
            for m in re.finditer(r"(?m)^  ([a-z][a-z0-9_]*):", text):
                add(m.group(1), name)
        elif base == "package.json":
            for m in re.finditer(r'"(@?[\w./-]+)"\s*:\s*"', text):
                n = m.group(1)
                add(n, name)
                if n.startswith("@capacitor/"):
                    add("capacitor", name)
                if n.startswith("cordova"):
                    add("cordova", name)
    return found


def apple_third_party_sdk_manifest(p: Project, a: dict):
    if not p.has_ios:
        return []
    deps = _dependency_names(p)
    listed = [s for s in a["sdks"] if s.lower() in deps]
    if not listed:
        return []
    return [(deps[listed[0].lower()], "uses SDKs on Apple's privacy-manifest list: " + ", ".join(listed[:12])
             + (" ..." if len(listed) > 12 else ""))]


def apple_private_api(p: Project, a: dict):
    if not p.has_ios:
        return []
    return [(h, "references Apple's private frameworks") for h in p.find_in_files(a["pattern"], None, 3)]


def apple_web_engine(p: Project, a: dict):
    if not p.has_ios:
        return []
    if any(k.startswith("com.apple.developer.web-browser-engine") for _, d in p.entitlements for k in d):
        return []
    hit = p.find_signal(a["pattern"])
    return [(hit, "embeds a non-WebKit browser engine")] if hit else []


def apple_ipad_support(p: Project, a: dict):
    out = []
    for label, d in _real_ios_plists(p):
        fam = d.get("UIDeviceFamily")
        if isinstance(fam, list) and fam and all(str(x) == "1" for x in fam):
            out.append((label, "UIDeviceFamily lists only iPhone"))
    if out:
        return out
    vals, where = [], "(project)"
    for f in p.config_files:
        if f.name == "project.pbxproj":
            vals += re.findall(r"TARGETED_DEVICE_FAMILY\s*=\s*\"?([\d,]+)\"?", f.read_text(encoding="utf-8", errors="ignore"))
            where = f.relative_to(p.root).as_posix()
    if vals and all(v == "1" for v in vals):
        out.append((where, "every target in the project is iPhone only (TARGETED_DEVICE_FAMILY = 1)"))
    return out


def apple_iap_restore(p: Project, a: dict):
    if not p.has_ios:
        return []
    hit = p.find_signal(a["iap"])
    if not hit or p.find_signal(a["restore"]):
        return []
    return [(hit, "in-app purchase code found but no restore-purchases code")]


_DO_OPEN = re.compile(r"\bdo(?:\s*\|[^|]*\|)?\s*$")
_TARGET = re.compile(r"^\s*(?:abstract_)?target\s+['\"]([^'\"]+)['\"]\s+do\b")


def apple_ads_in_extensions(p: Project, a: dict):
    """Display advertising belongs in the main app binary, not in extensions, widgets, App Clips or watch apps."""
    if not p.has_ios:
        return []
    ad, ext = re.compile(a["ad_pods"]), re.compile(a["extension_targets"])
    out = []
    for name, text, lock in p.texts:
        if lock or name.replace("\\", "/").rsplit("/", 1)[-1].lower() != "podfile":
            continue
        stack: list[str | None] = []
        for line in text.splitlines():
            line = line.split("#", 1)[0]
            m = _TARGET.match(line)
            if m:
                stack.append(m.group(1))
                continue
            if re.match(r"^\s*end\b", line):
                if stack:
                    stack.pop()
                continue
            if _DO_OPEN.search(line.rstrip()):
                stack.append(None)
                continue
            pm = re.match(r"^\s*pod\s+['\"]([^'\"]+)['\"]", line)
            if pm and ad.search(pm.group(1)):
                targets = [t for t in stack if t]
                if any(ext.search(t) for t in targets):
                    out.append((name, f"ad SDK '{pm.group(1)}' is in the extension target '{next(t for t in targets if ext.search(t))}'"))
    return out


def apple_health_data_ads(p: Project, a: dict):
    if not p.has_ios:
        return []
    h, ad = p.find_signal(a["health"]), p.find_signal(a["ads"])
    return [(h, f"health or fitness data APIs and an ad SDK ({ad}) are both present")] if h and ad else []


def both_kids_third_party_sdks(p: Project, a: dict):
    flag = p.find_signal(a["child_signal"])
    if not flag:
        return []
    from . import privacy
    names = []
    for sig in privacy.DATA["signals"]:
        if sig["id"] in a["sdk_ids"]:
            hits = [h for h in p.find_signals(sig["pattern"], limit=400) if privacy._evidence_ok(h)]
            if hits:
                names.append(sig["name"])
    if not names:
        return []
    return [(flag, "child-directed signals found together with third-party analytics/ad SDKs: " + ", ".join(names))]


def apple_vpn_app(p: Project, a: dict):
    hit = p.find_signal(a["pattern"]) if p.has_ios else None
    return [(hit, "VPN code found")] if hit else []


def apple_screen_recording_consent(p: Project, a: dict):
    hit = p.find_signal(a["pattern"]) if p.has_ios else None
    return [(hit, "screen recording code found")] if hit else []


_LOCAL = re.compile(r"^https?://(?:localhost|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|[^/]*\.local\b)", re.I)


def both_remote_web_content(p: Project, a: dict):
    """Apps whose main content is a remote website: Apple 4.2 / 4.2.2 and Google Play's Spam policy (web views)."""
    out = []
    for name, text, lock in p.texts:
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if re.fullmatch(r"capacitor\.config\.(json|ts|js)", base):
            m = re.search(r"server['\"]?\s*:\s*\{[^}]*?url['\"]?\s*:\s*['\"](https?://[^'\"]+)", text, re.S)
            if m and not _LOCAL.match(m.group(1)):
                out.append((name, f"Capacitor loads a remote site as the app: {m.group(1)[:60]}"))
        elif base == "config.xml":
            m = re.search(r"<content\s+[^>]*src\s*=\s*['\"](https?://[^'\"]+)", text)
            if m and not _LOCAL.match(m.group(1)):
                out.append((name, f"Cordova content src is a remote site: {m.group(1)[:60]}"))
    if not out:
        acts = 0
        for _, root in _manifest_roots(p):
            app = root.find("application")
            acts += len([x for x in (app if app is not None else []) if x.tag == "activity"
                         and x.get(TOOLS + "node") != "remove"])
        if acts == 1:
            hit = p.find_in_files(a["load_url"], (".kt", ".java"), 1)
            if hit:
                out.append((hit[0], "the app's only activity loads a remote website in a web view"))
    return out


def play_webview_js_interface(p: Project, a: dict):
    if not p.has_android:
        return []
    return [(h, "exposes an object to web content with addJavascriptInterface")
            for h in p.find_in_files(a["pattern"], (".kt", ".java"), 3)]


CHECKS_EXTRA = {f.__name__: f for f in (
    apple_ads_in_extensions, apple_health_data_ads, both_kids_third_party_sdks, apple_vpn_app,
    apple_screen_recording_consent, both_remote_web_content, play_webview_js_interface,
    apple_required_reason_api, apple_third_party_sdk_manifest, apple_private_api, apple_web_engine,
    apple_ipad_support, apple_iap_restore,
    android_exported_missing, android_fgs_type_missing, android_release_debug_signing, ios_app_icon,
    ios_launch_screen, ios_deployment_target, ios_xcode_version, ios_push_entitlement, ios_background_modes,
    payments_without_iap, listing_limits, listing_screenshots, privacy_policy, ugc_without_moderation)}
