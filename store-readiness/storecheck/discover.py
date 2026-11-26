"""Language-agnostic project discovery.

Nothing here parses source code. It finds the files app stores inspect
(manifests, plists, Gradle files, built archives, native libraries) and keeps
text for pattern searches that work in any language.
"""
from __future__ import annotations

import plistlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".gradle", "build", "Pods", "DerivedData",
             ".dart_tool", ".idea", "__pycache__", "venv", ".venv", "dist", "out",
             "target", ".next"}
VENDORED = ("/pods/", "/carthage/", "/thirdparty/", "/third_party/", "/third-party/", "/vendor/", "/external/")
OTHER_PLATFORM_DIRS = ("macos", "osx", "linux", "windows", "android", "web")
BUILD_ARTIFACT_DIRS = ("outputs", "ios/ipa", "app/outputs")
MAX_TEXT_BYTES = 512 * 1024
MAX_TEXT_FILES = 20000
ELF_HEAD = 8192
from struct import error as struct_error


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.frameworks: set[str] = set()
        self.android_manifests: list[Path] = []
        self.gradle_files: list[Path] = []
        self.plists: list[tuple[str, dict]] = []      # (label, parsed app Info.plist)
        self.has_privacy_manifest = False
        self.has_ios_project = False
        self.artifacts: list[Path] = []
        self.native_libs: list[tuple[str, bytes]] = []  # (label, first bytes of .so)
        self.texts: list[tuple[str, str, bool]] = []  # (path, text, is_lockfile)
        self.sdk_sources: list[tuple[str, str]] = []  # files that may define targetSdk
        self.notes: list[str] = []
        self.config_files: list[Path] = []            # project.pbxproj, app.json, config.xml, ...
        self.extra_permissions: list[tuple[str, str]] = []  # (where, short name) from config files
        self.synthetic_plists: dict[str, str] = {}    # label -> note, plists inferred from config
        self.android_hint = False                     # Android configured in a config file
        self.archive_manifests: list[tuple[str, "ET.Element"]] = []   # decoded APK manifests
        self.entitlements: list[tuple[str, dict]] = []                 # *.entitlements plists
        self.privacy_manifests: list[tuple[str, dict]] = []            # parsed PrivacyInfo.xcprivacy files
        self.declared_privacy_apis: set[str] = set()                   # categories declared in config (Expo)
        self.appicon_sets: list[Path] = []                             # Contents.json of *.appiconset
        self.has_icon_composer = False                                 # Xcode 26 *.icon bundle
        self.listing_files: list[Path] = []                            # fastlane / F-Droid store text files
        self.screenshots: list[Path] = []                              # store screenshot images
        self.localized_plist_keys: set[str] = set()   # usage keys found in InfoPlist.strings
        self.passed: list[tuple[str, str]] = []
        self._search_cache: dict[tuple, str | None] = {}

    # --- platform footprint -------------------------------------------------
    @property
    def has_android(self) -> bool:
        return bool(self.android_manifests or self.gradle_files or self.android_hint or
                    any(a.suffix in (".apk", ".aab") for a in self.artifacts))

    @property
    def has_ios(self) -> bool:
        return self.has_ios_project or bool(self.plists) or \
            any(a.suffix == ".ipa" for a in self.artifacts)

    def find_signals(self, pattern: str, limit: int = 3, locks: bool = True) -> list[str]:
        rx = re.compile(pattern)
        out = []
        for name, text, is_lock in self.texts:
            if (is_lock and not locks) or _is_ci_path(name):
                continue
            if rx.search(text):
                out.append(name)
                if len(out) >= limit:
                    break
        return out

    def find_in_files(self, pattern: str, suffixes: tuple[str, ...] | None = None, limit: int = 3,
                      skip_platform_dirs: bool = False) -> list[str]:
        """Files (not lockfiles, tests, docs, CI or vendored dirs) whose text matches, optionally by file suffix."""
        rx = re.compile(pattern)
        out = []
        for name, text, is_lock in self.texts:
            low = "/" + name.replace("\\", "/").lower()
            if is_lock or _is_ci_path(name) or any(x in low for x in VENDORED):
                continue
            if suffixes and not low.endswith(suffixes):
                continue
            if skip_platform_dirs and any(f"/{d}/" in low for d in OTHER_PLATFORM_DIRS):
                continue
            if rx.search(text):
                out.append(name)
                if len(out) >= limit:
                    break
        return out

    # --- text signal search (any language) ---------------------------------
    def find_signal(self, pattern: str, locks: bool = False) -> str | None:
        """First file whose text matches `pattern` (lockfiles only if locks=True), else None."""
        key = (pattern, locks)
        if key not in self._search_cache:
            rx = re.compile(pattern)
            self._search_cache[key] = next(
                (name for name, text, is_lock in self.texts
                 if (locks or not is_lock) and not _is_ci_path(name) and rx.search(text)), None)
        return self._search_cache[key]


_TEST_DIR_RX = re.compile(r"(?i)(^|/)(tests?|__tests__|__mocks__|mocks?|androidtest|unittests?|uitests?|e2e|fixtures)(/|$)"
                          r"|[^/]*tests?(/|$)|(^|/)(mock|fake)[^/]*$")
_TEST_FILE_RX = re.compile(r"[a-z]Tests?\.[A-Za-z]+$|[._-](test|tests|spec)\.[A-Za-z]+$")
# translation/vector/data files never hold code signals; skipping them is the biggest scan-time saving
_DATA_SUFFIXES = {".map", ".strings", ".stringsdict", ".xcstrings", ".pdf", ".svg", ".po", ".xliff", ".csv"}
_DOC_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc"}
_LOCK_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pubspec.lock", "podfile.lock",
               "cargo.lock", "gemfile.lock", "package.resolved", "composer.lock", "bun.lockb"}
# Info.plist is often renamed per build variant: Wikipedia-Info.plist, Info-iOS.plist, Alpha-Info.plist
_INFO_PLIST_RX = re.compile(r"(?i)^(.*[-_.])?info([-_.].*)?\.plist$")
LISTING_NAMES = {"name.txt", "subtitle.txt", "description.txt", "keywords.txt", "promotional_text.txt",
                 "title.txt", "short_description.txt", "full_description.txt", "privacy_url.txt"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_CONFIG_NAMES = {"project.pbxproj", "app.json", "config.xml", "ProjectSettings.asset", "export_presets.cfg"}
_APP_CONFIG_RX = re.compile(r"(app\.config\.(js|ts|json|mjs|cjs)|nativescript\.config\.(js|ts|json)|[^/]+\.csproj)$")
_SDK_NAMES = {"build.gradle", "build.gradle.kts", "variables.gradle", "gradle.properties", "libs.versions.toml",
              "app.gradle"}   # app.gradle: NativeScript App_Resources/Android


def _is_ci_path(rel: str) -> bool:
    """CI and repo-automation files (GitHub Actions scripts and so on) are not app code."""
    low = "/" + rel.replace("\\", "/").lower()
    return any(x in low for x in ("/.github/", "/.circleci/", "/.gitlab/", "/.buildkite/", "/fastlane/"))


def _is_test_path(p: Path) -> bool:
    parts = {x.lower() for x in p.parts}
    return bool(parts & {"test", "tests", "androidtest", "debug", "uitests"}) or \
        any(x.endswith("tests") for x in parts)


def _is_test_rel(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return bool(_TEST_DIR_RX.search(rel) or _TEST_FILE_RX.search(rel))


def _load_plist(data: bytes) -> dict | None:
    try:
        d = plistlib.loads(data)
    except Exception:
        return None
    return d if isinstance(d, dict) else None


_FIREBASE_KEYS = {"GCM_SENDER_ID", "GOOGLE_APP_ID", "BUNDLE_ID", "PROJECT_ID", "API_KEY", "CLIENT_ID"}


_NON_ANDROID_LIB = re.compile(r"(?i)(^|[/._-])(linux|windows|win32|win64|macos|osx|darwin|ios|wasm|web)([/._-]|$)")
_ANDROID_LIB = re.compile(r"(?i)jnilibs|android|arm64-v8a|armeabi|/lib/x86(_64)?/")


def _is_android_lib_path(rel: str) -> bool:
    """A source-tree .so counts as an Android library only if its path says so; desktop plugin
    binaries (addons/.../linux/x86_64/*.so) are x86-64 ELF too but never ship in an APK."""
    low = "/" + rel.lower()
    if _ANDROID_LIB.search(low) and not re.search(r"(?i)/(linux|windows|macos|osx|darwin)/", low):
        return True
    return not _NON_ANDROID_LIB.search(low) and "/lib/" in low and "arm64-v8a" in low


def _is_app_plist(d: dict) -> bool:
    """An app's Info.plist, not a framework, test bundle, app extension or Firebase config.

    Generated-plist projects keep only a few extra keys in the file (or none), so no particular key is required."""
    return ("NSExtension" not in d
            and "AvailableLibraries" not in d      # .xcframework container, not an app
            and d.get("CFBundlePackageType") not in ("FMWK", "BNDL")
            and not (_FIREBASE_KEYS & set(d)))


def discover(path: str | Path) -> Project:
    path = Path(path)
    proj = Project(path)
    if path.is_file():
        _scan_archive(proj, path)
        return proj
    for f in _walk(path):
        rel = f.relative_to(path).as_posix()
        name, suffix = f.name, f.suffix.lower()
        if name == "AndroidManifest.xml" and not _is_test_path(f.relative_to(path)):
            proj.android_manifests.append(f)
        elif name in ("build.gradle", "build.gradle.kts"):
            proj.gradle_files.append(f)
        elif _INFO_PLIST_RX.match(name) and not _is_test_path(f.relative_to(path)):
            d = _load_plist(f.read_bytes())
            if d is not None and _is_app_plist(d):
                proj.plists.append((rel, d))
        elif name == "PrivacyInfo.xcprivacy":
            proj.has_privacy_manifest = True
            d = _load_plist(f.read_bytes())
            if d is not None:
                proj.privacy_manifests.append((rel, d))
        elif suffix in (".xcodeproj", ".xcworkspace") or name in ("Podfile", "Package.swift"):
            proj.has_ios_project = True
        elif suffix in (".apk", ".aab", ".ipa"):
            proj.artifacts.append(f)
            _scan_archive(proj, f)
        elif suffix == ".so" and _is_android_lib_path(rel):
            with open(f, "rb") as fh:
                proj.native_libs.append((rel, fh.read(ELF_HEAD)))
        _collect_store_assets(proj, f, rel, name, suffix)
        if name.lower() == "infoplist.strings" and not _is_test_rel(rel):
            _read_localized_keys(proj, f)
        if (name in _CONFIG_NAMES or suffix == ".xcconfig" or _APP_CONFIG_RX.match(name)) \
                and not _is_test_rel(rel):
            proj.config_files.append(f)
        _maybe_read_text(proj, f, rel)
    _detect_frameworks(proj, path)
    from . import frameworks
    frameworks.apply(proj)
    _drop_dev_plists(proj)
    if proj.has_ios_project and not proj.plists:
        proj.notes.append("iOS project found but no app Info.plist: usage-string, ATS, version and "
                          "export-compliance checks were skipped.")
    return proj


def _collect_store_assets(proj: Project, f: Path, rel: str, name: str, suffix: str) -> None:
    parts = [x.lower() for x in Path(rel).parts]
    if suffix == ".entitlements":
        d = _load_plist(f.read_bytes())
        if d is not None:
            proj.entitlements.append((rel, d))
    elif name == "Contents.json" and f.parent.name.endswith(".appiconset"):
        proj.appicon_sets.append(f)
    if any(x.endswith(".icon") for x in parts[:-1]):
        proj.has_icon_composer = True
    in_listing = "metadata" in parts[:-1] or "fastlane" in parts[:-1]
    if name in LISTING_NAMES and in_listing:
        proj.listing_files.append(f)
    elif suffix in IMAGE_SUFFIXES and in_listing and any("screenshots" in x for x in parts[:-1]):
        proj.screenshots.append(f)


def _read_localized_keys(proj: Project, f: Path) -> None:
    try:
        raw = f.read_bytes()[:200_000]
    except OSError:
        return
    for enc in ("utf-16", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return
    proj.localized_plist_keys.update(re.findall(r"\"?(NS[A-Za-z]+UsageDescription)\"?\s*=", text))


_DEV_PLIST_RX = re.compile(r"(?i)(^|[/\\])([^/\\]*[-_.])?(local|debug|dev|development)([-_.][^/\\]*)?info[^/\\]*\.plist$|"
                           r"(^|[/\\])info[-_.](local|debug|dev|development)[^/\\]*\.plist$")


def _drop_dev_plists(proj: Project) -> None:
    """Local/debug build variants (e.g. Local-Info.plist) are not shipped: ignore them when a release plist exists."""
    dev = [(l, d) for l, d in proj.plists if _DEV_PLIST_RX.search(l)]
    keep = [(l, d) for l, d in proj.plists if not _DEV_PLIST_RX.search(l)]
    if dev and keep:
        proj.plists = keep
        proj.notes.append("Ignored development-variant plists: " + ", ".join(l for l, _ in dev))


def _walk(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                if e.suffix in (".xcodeproj", ".xcworkspace"):
                    yield e
                if e.is_symlink():
                    continue
                if e.name not in SKIP_DIRS:
                    stack.append(e)
                elif e.name == "build":
                    # build output is skipped, except where built APK/AAB/IPA artifacts are normally written
                    stack.extend(e / sub for sub in BUILD_ARTIFACT_DIRS if (e / sub).is_dir())
            else:
                yield e


def _maybe_read_text(proj: Project, f: Path, rel: str) -> None:
    low = f.name.lower()
    if f.suffix.lower() in _DOC_SUFFIXES or f.suffix.lower() in _DATA_SUFFIXES or _is_test_rel(rel) \
            or low.endswith((".min.js", ".min.css")):   # minified third-party bundles only add false signals
        return
    if len(proj.texts) >= MAX_TEXT_FILES:
        return
    try:
        if f.stat().st_size > MAX_TEXT_BYTES:
            return
        raw = f.read_bytes()
    except OSError:
        return
    if b"\0" in raw[:1024]:
        return
    text = raw.decode("utf-8", errors="ignore")
    proj.texts.append((rel, text, low in _LOCK_NAMES or low.endswith(".lock")))
    in_build_logic = any(x in ("build-logic", "buildSrc") for x in Path(rel).parts)
    if low in _SDK_NAMES or (in_build_logic and f.suffix in (".kt", ".kts", ".gradle")):
        proj.sdk_sources.append((rel, text))


def _scan_archive(proj: Project, f: Path) -> None:
    if f not in proj.artifacts:
        proj.artifacts.append(f)
    try:
        z = zipfile.ZipFile(f)
    except (zipfile.BadZipFile, OSError):
        proj.notes.append(f"{f.name}: not a readable zip archive")
        return
    with z:
        for n in z.namelist():
            low = n.lower()
            if low.endswith(".so"):
                with z.open(n) as fh:
                    proj.native_libs.append((f"{f.name}!{n}", fh.read(ELF_HEAD)))
            elif low.endswith("info.plist") and ".app/" in low and low.count("/") == 2:
                d = _load_plist(z.read(n))
                if d is not None and _is_app_plist(d):
                    proj.plists.append((f"{f.name}!{n}", d))
            elif low.endswith("privacyinfo.xcprivacy") and ".app/" in low:
                proj.has_privacy_manifest = True
    if f.suffix.lower() == ".apk":
        try:
            from .axml import AxmlError, decode_axml
            with zipfile.ZipFile(f) as z:
                proj.archive_manifests.append((f"{f.name}!AndroidManifest.xml",
                                               decode_axml(z.read("AndroidManifest.xml"))))
        except (AxmlError, KeyError, OSError, zipfile.BadZipFile, struct_error) as e:
            proj.notes.append(f"{f.name}: could not decode AndroidManifest.xml ({e}); manifest checks skipped.")
    elif f.suffix.lower() == ".aab":
        from .pbxml import PbxmlError, decode_proto_manifest
        try:
            with zipfile.ZipFile(f) as z:
                names = [n for n in z.namelist() if n.endswith("/manifest/AndroidManifest.xml")]
                for n in names:
                    proj.archive_manifests.append((f"{f.name}!{n}", decode_proto_manifest(z.read(n))))
            if not names:
                proj.notes.append(f"{f.name}: no module manifest found; manifest checks skipped.")
        except (PbxmlError, OSError, zipfile.BadZipFile) as e:
            proj.notes.append(f"{f.name}: could not decode the bundle manifest ({e}); manifest checks skipped.")


def _detect_frameworks(proj: Project, root: Path) -> None:
    markers = {
        "flutter": "pubspec.yaml", "unity": "ProjectSettings",
        "capacitor": "capacitor.config.json",
    }
    for fw, marker in markers.items():
        if (root / marker).exists():
            proj.frameworks.add(fw)
    if any((root / f"capacitor.config.{x}").exists() for x in ("ts", "js")):
        proj.frameworks.add("capacitor")
    pkg = root / "package.json"
    if pkg.exists():
        txt = pkg.read_text(encoding="utf-8", errors="ignore")
        if "react-native" in txt:
            proj.frameworks.add("react-native")
        if re.search(r"@nativescript/core|tns-core-modules|\"nativescript\"\s*:", txt):
            proj.frameworks.add("nativescript")
    if (root / "Cargo.toml").exists():
        proj.frameworks.add("rust")
