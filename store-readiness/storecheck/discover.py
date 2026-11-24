"""Language-agnostic project discovery.

Nothing here parses source code. It finds the files app stores inspect
(manifests, plists, Gradle files, built archives, native libraries) and keeps
text for pattern searches that work in any language.
"""
from __future__ import annotations

import plistlib
import re
import zipfile
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".gradle", "build", "Pods", "DerivedData",
             ".dart_tool", ".idea", "__pycache__", "venv", ".venv", "dist", "out",
             "target", ".next"}
MAX_TEXT_BYTES = 512 * 1024
MAX_TEXT_FILES = 20000
ELF_HEAD = 8192


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
        self.texts: list[tuple[str, str]] = []
        self.notes: list[str] = []
        self._search_cache: dict[str, str | None] = {}

    # --- platform footprint -------------------------------------------------
    @property
    def has_android(self) -> bool:
        return bool(self.android_manifests or self.gradle_files or
                    any(a.suffix in (".apk", ".aab") for a in self.artifacts))

    @property
    def has_ios(self) -> bool:
        return self.has_ios_project or bool(self.plists) or \
            any(a.suffix == ".ipa" for a in self.artifacts)

    def find_signals(self, pattern: str, limit: int = 3) -> list[str]:
        rx = re.compile(pattern)
        out = []
        for name, text in self.texts:
            if rx.search(text):
                out.append(name)
                if len(out) >= limit:
                    break
        return out

    # --- text signal search (any language) ---------------------------------
    def find_signal(self, pattern: str) -> str | None:
        """Return the first file whose text matches `pattern`, else None."""
        if pattern not in self._search_cache:
            rx = re.compile(pattern)
            self._search_cache[pattern] = next(
                (name for name, text in self.texts if rx.search(text)), None)
        return self._search_cache[pattern]


def _is_test_path(p: Path) -> bool:
    parts = {x.lower() for x in p.parts}
    return bool(parts & {"test", "tests", "androidtest", "debug", "uitests"}) or \
        any(x.endswith("tests") for x in parts)


def _load_plist(data: bytes) -> dict | None:
    try:
        d = plistlib.loads(data)
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _is_app_plist(d: dict) -> bool:
    return "CFBundleIdentifier" in d and "NSExtension" not in d


def discover(path: str | Path) -> Project:
    path = Path(path)
    proj = Project(path)
    if path.is_file():
        _scan_archive(proj, path)
        return proj
    for f in _walk(path):
        rel = str(f.relative_to(path))
        name, suffix = f.name, f.suffix.lower()
        if name == "AndroidManifest.xml" and not _is_test_path(f.relative_to(path)):
            proj.android_manifests.append(f)
        elif name in ("build.gradle", "build.gradle.kts"):
            proj.gradle_files.append(f)
        elif name == "Info.plist" and not _is_test_path(f.relative_to(path)):
            d = _load_plist(f.read_bytes())
            if d is not None and _is_app_plist(d):
                proj.plists.append((rel, d))
        elif name == "PrivacyInfo.xcprivacy":
            proj.has_privacy_manifest = True
        elif suffix in (".xcodeproj", ".xcworkspace") or name in ("Podfile", "Package.swift"):
            proj.has_ios_project = True
        elif suffix in (".apk", ".aab", ".ipa"):
            proj.artifacts.append(f)
            _scan_archive(proj, f)
        elif suffix == ".so":
            with open(f, "rb") as fh:
                proj.native_libs.append((rel, fh.read(ELF_HEAD)))
        _maybe_read_text(proj, f, rel)
    _detect_frameworks(proj, path)
    return proj


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
                if e.name not in SKIP_DIRS and not e.is_symlink():
                    stack.append(e)
            else:
                yield e


def _maybe_read_text(proj: Project, f: Path, rel: str) -> None:
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
    proj.texts.append((rel, raw.decode("utf-8", errors="ignore")))


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
    if f.suffix.lower() in (".apk", ".aab"):
        proj.notes.append(f"{f.name}: AndroidManifest inside archives is binary XML and is "
                          "not decoded; point storecheck at the source project for manifest checks.")


def _detect_frameworks(proj: Project, root: Path) -> None:
    markers = {
        "flutter": "pubspec.yaml", "unity": "ProjectSettings", "cordova/capacitor": "config.xml",
        "capacitor": "capacitor.config.json", "expo": "app.json",
    }
    for fw, marker in markers.items():
        if (root / marker).exists():
            proj.frameworks.add(fw)
    pkg = root / "package.json"
    if pkg.exists() and "react-native" in pkg.read_text(errors="ignore"):
        proj.frameworks.add("react-native")
    if (root / "Cargo.toml").exists():
        proj.frameworks.add("rust")
