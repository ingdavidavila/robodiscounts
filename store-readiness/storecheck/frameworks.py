"""Config-driven projects: Xcode-generated Info.plist keys, Expo, Unity and Cordova.

These projects often have no AndroidManifest.xml or Info.plist in the repo; the build tool
creates them from a config file. This module reads that config as plain text (it never
executes app.config.js or any other code) and fills the same Project fields the file-based
discovery fills, so every rule works unchanged.

Anything inferred from config is marked in `project.synthetic_plists`, so rules can report
it with lower certainty than a real Info.plist.

The Expo plugin/option names, the Unity field names and the Cordova plugin variable names
below come from memory of those tools' docs and are NOT yet verified.
"""
from __future__ import annotations

import re
from pathlib import Path

from .discover import Project

_NS_KEY = re.compile(r"\bNS[A-Za-z]+UsageDescription\b")
_ITS = re.compile(r"ITSAppUsesNonExemptEncryption|usesNonExemptEncryption")

# Expo config-plugin options that become Info.plist usage strings
EXPO_OPTION_KEYS = {
    "cameraPermission": "NSCameraUsageDescription",
    "microphonePermission": "NSMicrophoneUsageDescription",
    "photosPermission": "NSPhotoLibraryUsageDescription",
    "locationWhenInUsePermission": "NSLocationWhenInUseUsageDescription",
    "locationAlwaysAndWhenInUsePermission": "NSLocationAlwaysAndWhenInUseUsageDescription",
    "contactsPermission": "NSContactsUsageDescription",
    "faceIDPermission": "NSFaceIDUsageDescription",
    "userTrackingPermission": "NSUserTrackingUsageDescription",
    "calendarsPermission": "NSCalendarsUsageDescription",
}
# Expo plugins that add default usage strings even when no option is given
EXPO_PLUGIN_DEFAULTS = {
    "expo-camera": ["NSCameraUsageDescription", "NSMicrophoneUsageDescription"],
    "expo-image-picker": ["NSCameraUsageDescription", "NSPhotoLibraryUsageDescription",
                          "NSMicrophoneUsageDescription"],
    "expo-location": ["NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription"],
    "expo-contacts": ["NSContactsUsageDescription"],
    "expo-media-library": ["NSPhotoLibraryUsageDescription"],
    "expo-av": ["NSMicrophoneUsageDescription"],
    "expo-local-authentication": ["NSFaceIDUsageDescription"],
    "expo-tracking-transparency": ["NSUserTrackingUsageDescription"],
    "expo-calendar": ["NSCalendarsUsageDescription"],
}
UNITY_FIELD_KEYS = {
    "cameraUsageDescription": "NSCameraUsageDescription",
    "locationUsageDescription": "NSLocationWhenInUseUsageDescription",
    "microphoneUsageDescription": "NSMicrophoneUsageDescription",
}
CORDOVA_VARIABLE_KEYS = {
    "CAMERA_USAGE_DESCRIPTION": "NSCameraUsageDescription",
    "PHOTOLIBRARY_USAGE_DESCRIPTION": "NSPhotoLibraryUsageDescription",
    "MICROPHONE_USAGE_DESCRIPTION": "NSMicrophoneUsageDescription",
    "LOCATION_WHEN_IN_USE_DESCRIPTION": "NSLocationWhenInUseUsageDescription",
    "CONTACTS_USAGE_DESCRIPTION": "NSContactsUsageDescription",
    "GEOLOCATION_USAGE_DESCRIPTION": "NSLocationWhenInUseUsageDescription",
    "BLUETOOTH_USAGE_DESCRIPTION": "NSBluetoothAlwaysUsageDescription",
}


def _read(f: Path, limit: int = 8 * 1024 * 1024) -> str:
    try:
        if f.stat().st_size > limit:
            return ""
        return f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _rel(proj: Project, f: Path) -> str:
    return f.relative_to(proj.root).as_posix()


def _add_synthetic(proj: Project, label: str, keys: dict, note: str) -> None:
    proj.plists.append((label, keys))
    proj.synthetic_plists[label] = note


def apply(proj: Project) -> None:
    # Mac Catalyst plists describe a macOS app, not the iOS build (e.g. .NET MAUI Platforms/MacCatalyst)
    proj.plists = [(l, d) for l, d in proj.plists if "/maccatalyst/" not in "/" + l.lower().replace("\\", "/")]
    _xcode(proj)
    if proj.localized_plist_keys:   # keys localized in InfoPlist.strings count as present
        proj.plists = [(label, {**{k: "localized" for k in proj.localized_plist_keys}, **d})
                       for label, d in proj.plists]
    real_plists = bool(proj.plists)
    _expo(proj, real_plists)
    _unity(proj, real_plists)
    _cordova(proj, real_plists)
    _maui(proj)
    _godot(proj)
    _kmp(proj)


# --- Xcode-generated Info.plist -----------------------------------------------------------
def _xcode(proj: Project) -> None:
    overlay: dict[str, str] = {}
    generated = False
    bundle_id = None
    for f in proj.config_files:
        if f.name != "project.pbxproj" and f.suffix != ".xcconfig":
            continue
        text = _read(f)
        for m in re.finditer(r"INFOPLIST_KEY_(\w+)(?:\[[^\]]*\])?\"?\s*=\s*([^;\n]+)", text):
            val = m.group(2).strip().strip('"').strip()
            if val:
                overlay.setdefault(m.group(1), val)
        m = re.search(r"MARKETING_VERSION\s*=\s*([^;\n]+)", text)
        if m:
            overlay.setdefault("CFBundleShortVersionString", m.group(1).strip().strip('"'))
        m = re.search(r"CURRENT_PROJECT_VERSION\s*=\s*([^;\n]+)", text)
        if m:
            overlay.setdefault("CFBundleVersion", m.group(1).strip().strip('"'))
        generated |= bool(re.search(r"GENERATE_INFOPLIST_FILE\s*=\s*YES", text))
        m = re.search(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([^;\n]+)", text)
        if m and not bundle_id:
            bundle_id = m.group(1).strip().strip('"')
    if not overlay and not generated:
        return
    proj.has_ios_project = True
    if proj.plists:
        # Xcode merges generated keys into the plist file; keys already in the file win
        proj.plists = [(label, {**overlay, **d}) for label, d in proj.plists]
    elif generated:
        keys = {**overlay, "CFBundleIdentifier": bundle_id or "generated"}
        _add_synthetic(proj, "project.pbxproj (generated Info.plist)", keys,
                       "Info.plist is generated from build settings; keys from all targets are merged")


# --- Expo ----------------------------------------------------------------------------------
def _expo(proj: Project, real_plists: bool) -> None:
    pkg = proj.root / "package.json"
    pkg_text = _read(pkg) if pkg.exists() else ""
    for f in proj.config_files:
        rel = _rel(proj, f)
        is_json = f.name == "app.json"
        is_cfg = re.fullmatch(r"app\.config\.(js|ts|json|mjs|cjs)", f.name) is not None
        if not (is_json or is_cfg):
            continue
        text = _read(f)
        if is_json and '"expo"' not in text:
            continue                       # plain React Native app.json
        if is_cfg and '"expo"' not in pkg_text and "expo" not in text:
            continue
        proj.frameworks.add("expo")
        proj.sdk_sources.append((rel, text))
        if not is_json:
            proj.notes.append(f"{rel}: read as text, not executed; values computed in code are not seen.")
        # Android permissions requested in config
        for m in re.finditer(r"permissions[\"']?\s*:\s*\[([^\]]*)\]", text):
            for pm in re.finditer(r"[\"']([A-Za-z_.]+)[\"']", m.group(1)):
                proj.extra_permissions.append((rel, pm.group(1).rsplit(".", 1)[-1]))
        has_android = bool(re.search(r"[\"']?android[\"']?\s*:", text))
        has_ios = bool(re.search(r"[\"']?ios[\"']?\s*:", text))
        if has_android:
            proj.android_hint = True
        if re.search(r"privacyManifests", text):
            proj.has_privacy_manifest = True
            proj.declared_privacy_apis.update(re.findall(r"NSPrivacyAccessedAPICategory\w+", text))
        if has_ios and not real_plists:
            keys = {"CFBundleIdentifier": "expo.app", "CFBundleShortVersionString": "expo",
                    "CFBundleVersion": "expo"}
            bm = re.search(r"bundleIdentifier[\"']?\s*:\s*[\"']([^\"']+)", text)
            if bm:
                keys["CFBundleIdentifier"] = bm.group(1)
            for k in _NS_KEY.findall(text):
                keys[k] = "set"
            if _ITS.search(text):
                keys["ITSAppUsesNonExemptEncryption"] = False
            for opt, plist_key in EXPO_OPTION_KEYS.items():
                if re.search(r"\b" + opt + r"\b", text):
                    keys[plist_key] = "set"
            for plugin, plist_keys in EXPO_PLUGIN_DEFAULTS.items():
                if re.search(r"[\"']" + re.escape(plugin) + r"[\"']", text):
                    for k in plist_keys:
                        keys.setdefault(k, "plugin default")
            _add_synthetic(proj, f"{rel} (Expo)", keys,
                           "Expo prebuild generates Info.plist from this config and its plugins")


# --- Unity ---------------------------------------------------------------------------------
def _unity(proj: Project, real_plists: bool) -> None:
    for f in proj.config_files:
        if f.name != "ProjectSettings.asset":
            continue
        rel = _rel(proj, f)
        text = _read(f)
        proj.frameworks.add("unity")
        ios_id = re.search(r"(?m)^\s*iPhone:\s*(\S+)", text)
        and_id = re.search(r"(?m)^\s*Android:\s*(\S+)", text)

        def configured(m):
            return bool(m) and not m.group(1).startswith("com.DefaultCompany")
        if configured(and_id):
            proj.android_hint = True
            t = re.search(r"AndroidTargetSdkVersion:\s*(\d+)", text)
            if t and int(t.group(1)) > 0:
                proj.sdk_sources.append((rel, f"targetSdkVersion = {t.group(1)}"))
        if configured(ios_id) and not real_plists:
            keys = {"CFBundleIdentifier": ios_id.group(1), "CFBundleShortVersionString": "unity",
                    "CFBundleVersion": "unity"}
            for field, plist_key in UNITY_FIELD_KEYS.items():
                m = re.search(r"(?m)^\s*" + field + r":[ \t]*(\S.*)$", text)
                if m and m.group(1).strip() not in ("{}", "''", '""'):
                    keys[plist_key] = "set"
            _add_synthetic(proj, f"{rel} (Unity)", keys,
                           "Unity writes Info.plist at build time from these settings and any post-build scripts")
        elif not configured(ios_id) and not configured(and_id):
            proj.notes.append(f"{rel}: Unity project still uses default bundle ids; "
                              "assuming it is not configured for Android or iOS.")


# --- Cordova -------------------------------------------------------------------------------
def _cordova(proj: Project, real_plists: bool) -> None:
    for f in proj.config_files:
        if f.name != "config.xml":
            continue
        text = _read(f)
        if "<widget" not in text or ("cordova" not in text and "<platform" not in text):
            continue
        rel = _rel(proj, f)
        if rel.endswith("src/main/res/xml/config.xml"):
            continue   # Capacitor/Cordova-generated Android resource, not the app's own config
        proj.frameworks.add("cordova")
        has_android = bool(re.search(r"<(platform|engine)\s+name=\"android\"", text))
        has_ios = bool(re.search(r"<(platform|engine)\s+name=\"ios\"", text))
        if has_android:
            proj.android_hint = True
        for m in re.finditer(r"<uses-permission[^>]*android:name=\"(?:android\.permission\.)?([A-Z_]+)\"", text):
            proj.extra_permissions.append((rel, m.group(1)))
        m = re.search(r"android-targetSdkVersion\"\s+value=\"(\d+)\"", text)
        if m:
            proj.sdk_sources.append((rel, f"targetSdkVersion = {m.group(1)}"))
        if has_ios and not real_plists:
            wm = re.search(r"<widget[^>]*\bid=\"([^\"]+)\"", text)
            keys = {"CFBundleIdentifier": wm.group(1) if wm else "cordova.app",
                    "CFBundleShortVersionString": "cordova", "CFBundleVersion": "cordova"}
            for k in _NS_KEY.findall(text):
                keys[k] = "set"
            if _ITS.search(text):
                keys["ITSAppUsesNonExemptEncryption"] = False
            # cordova-plugin-geolocation 2.x ships its own NSLocationWhenInUseUsageDescription (checked in
            # its plugin.xml for 2.0.0-2.4.3; absent from 3.0.0 on)
            g = re.search(r"name=\"cordova-plugin-geolocation\"[^>]*spec=\"[~^>=\s]*(\d+)\.", text)
            if g and int(g.group(1)) <= 2:
                keys["NSLocationWhenInUseUsageDescription"] = "plugin default"
            for var, plist_key in CORDOVA_VARIABLE_KEYS.items():
                if var in text:
                    keys[plist_key] = "set"
            _add_synthetic(proj, f"{rel} (Cordova)", keys,
                           "Cordova generates Info.plist from config.xml and plugin variables")


# --- .NET MAUI -----------------------------------------------------------------------------
_MAUI_TFM = re.compile(r"net\d+\.\d+-android(\d+(?:\.\d+)?)?")
_MAUI_NOTE = ("MAUI generates the version keys and launch screen at build time from the .csproj "
              "(ApplicationDisplayVersion, ApplicationVersion, MauiSplashScreen)")


def _maui(proj: Project) -> None:
    maui_dirs = []
    for f in proj.config_files:
        if f.suffix != ".csproj":
            continue
        text = _read(f)
        if not re.search(r"<UseMaui>\s*true", text, re.I):
            continue
        proj.frameworks.add("dotnet-maui")
        rel = _rel(proj, f)
        maui_dirs.append(rel.rsplit("/", 1)[0] + "/" if "/" in rel else "")
        for m in _MAUI_TFM.finditer(text):
            proj.android_hint = True
            if m.group(1):   # net8.0-android34.0: the number after "android" is the target API level
                proj.sdk_sources.append((rel, f"targetSdkVersion = {int(float(m.group(1)))}"))
    for i, (label, d) in enumerate(proj.plists):
        norm = label.replace("\\", "/")
        if "/platforms/ios/" in "/" + norm.lower() and any(norm.startswith(x) for x in maui_dirs):
            filled = {"CFBundleShortVersionString": "maui", "CFBundleVersion": "maui",
                      "UILaunchScreen": {}, **d}
            proj.plists[i] = (label, filled)
            proj.synthetic_plists[label] = _MAUI_NOTE


# --- Godot ---------------------------------------------------------------------------------
# Godot privacy/* export options that become Info.plist usage strings. Names read from real
# export_presets.cfg files; the Info.plist key each one writes is NOT yet verified against Godot's source.
GODOT_IOS_KEYS = {
    "microphone_usage_description": "NSMicrophoneUsageDescription",
    "camera_usage_description": "NSCameraUsageDescription",
    "location_usage_description": "NSLocationWhenInUseUsageDescription",
    "address_book_usage_description": "NSContactsUsageDescription",
    "calendar_usage_description": "NSCalendarsUsageDescription",
    "photos_library_usage_description": "NSPhotoLibraryUsageDescription",
}


def _godot(proj: Project) -> None:
    for f in proj.config_files:
        if f.name != "export_presets.cfg":
            continue
        rel = _rel(proj, f)
        text = _read(f)
        proj.frameworks.add("godot")
        # split into [preset.N] / [preset.N.options] blocks; the platform is in the first, options in the second
        platform = None
        for block in re.split(r"(?m)^\[preset\.\d+(?:\.options)?\]\s*$", text):
            m = re.search(r'(?m)^platform="([^"]+)"', block)
            if m:
                platform = m.group(1)
                continue
            if platform == "Android":
                proj.android_hint = True
                t = re.search(r'(?m)^gradle_build/target_sdk="(\d+)"', block)
                if t:
                    proj.sdk_sources.append((rel, f"targetSdkVersion = {t.group(1)}"))
                for pm in re.finditer(r"(?m)^permissions/([a-z_0-9]+)=true", block):
                    proj.extra_permissions.append((rel, pm.group(1).upper()))
            elif platform == "iOS" and not any(l.startswith(rel) for l, _ in proj.plists):
                bid = re.search(r'(?m)^application/bundle_identifier="([^"]+)"', block)
                keys = {"CFBundleIdentifier": bid.group(1) if bid else "godot.app",
                        "CFBundleShortVersionString": "godot", "CFBundleVersion": "godot",
                        "UILaunchScreen": {}}
                for opt, plist_key in GODOT_IOS_KEYS.items():
                    v = re.search(r'(?m)^privacy/' + opt + r'="(.+)"', block)
                    if v:
                        keys[plist_key] = "set"
                proj.has_ios_project = True
                _add_synthetic(proj, f"{rel} (Godot iOS)", keys,
                               "Godot writes Info.plist at export time from these preset options")


# --- Kotlin Multiplatform --------------------------------------------------------------------
def _kmp(proj: Project) -> None:
    for _, text in proj.sdk_sources:
        if re.search(r"kotlin\(\"multiplatform\"\)|org\.jetbrains\.kotlin\.multiplatform|kotlin-multiplatform|kotlinMultiplatform",
                     text):
            proj.frameworks.add("kotlin-multiplatform")
            return
