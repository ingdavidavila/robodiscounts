import json
import struct
import tempfile
import unittest
import zlib
import zipfile
from pathlib import Path

from axml_encoder import SAMPLE, encode
from storecheck import axml
from storecheck.engine import scan

NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'


def png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + b"\0\0\0" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def plist(extra=""):
    return ('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>a.b</string>'
            + extra + '</dict></plist>')


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def w(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def ids(self, store="both", target=None):
        _, f = scan(str(target or self.root), store)
        return f, {x.rule_id for x in f}


class AxmlTests(Base):
    def test_decodes_utf8_and_utf16_pools_with_typed_values(self):
        for utf8 in (True, False):
            root = axml.decode_axml(encode(SAMPLE, utf8))
            app = root.find("application")
            A = "{http://schemas.android.com/apk/res/android}"
            self.assertEqual(app.get(A + "debuggable"), "true")
            self.assertEqual(app.get(A + "usesCleartextTraffic"), "false")
            self.assertEqual(root.find("uses-sdk").get(A + "targetSdkVersion"), "33")
            self.assertEqual(app.findall("service")[1].get(A + "name"), "ünï.Fgs")

    def test_rejects_garbage(self):
        with self.assertRaises(axml.AxmlError):
            axml.decode_axml(b"not xml at all")

    def test_apk_manifest_is_checked(self):
        apk = self.root / "app.apk"
        with zipfile.ZipFile(apk, "w") as z:
            z.writestr("AndroidManifest.xml", encode(SAMPLE, True))
        f, ids = self.ids("google", apk)
        self.assertIn("play.debuggable", ids)
        self.assertIn("play.target_sdk", ids)          # 33 < 36
        self.assertIn("play.exported_missing", ids)    # .Svc has an intent-filter and no android:exported


class AndroidExtra(Base):
    def manifest(self, body, perms=""):
        self.w("app/src/main/AndroidManifest.xml",
               f'<manifest {NS}>{perms}<application>{body}</application></manifest>')

    def test_exported_rules(self):
        self.manifest('<activity android:name=".A"><intent-filter><category android:name="android.intent.category.LAUNCHER"/>'
                      '</intent-filter></activity>'
                      '<service android:name=".S" android:exported="false"><intent-filter/></service>'
                      '<receiver android:name=".R"/>')
        f, ids = self.ids("google")
        hits = [x.detail for x in f if x.rule_id == "play.exported_missing"]
        self.assertEqual(len(hits), 1)                      # only the activity: filter, no exported
        self.assertIn("activity .A", hits[0])

    def test_launcher_exported_false_is_flagged(self):
        self.manifest('<activity android:name=".A" android:exported="false"><intent-filter>'
                      '<category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>')
        f, _ = self.ids("google")
        self.assertTrue(any("LAUNCHER" in x.detail for x in f if x.rule_id == "play.exported_missing"))

    def test_exported_skipped_when_target_below_31(self):
        self.manifest('<activity android:name=".A"><intent-filter/></activity>')
        self.w("app/build.gradle", 'apply plugin: "com.android.application"\nandroid { defaultConfig { targetSdk 30 } }')
        _, ids = self.ids("google")
        self.assertNotIn("play.exported_missing", ids)

    def test_foreground_service_types(self):
        self.manifest('<service android:name=".A"/><service android:name=".B" android:foregroundServiceType="location"/>'
                      '<service android:name=".Tile" android:permission="android.permission.BIND_QUICK_SETTINGS_TILE"/>'
                      '<service android:name="androidx.appcompat.app.AppLocalesMetadataHolderService"/>'
                      '<service android:name=".Off" android:enabled="false"/>',
                      '<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>')
        _, ids = self.ids("google")
        self.assertNotIn("play.fgs_type", ids)           # no code starts a foreground service
        self.w("app/src/main/java/A.kt", "startForeground(1, notification)")
        f, _ = self.ids("google")
        d = [x.detail for x in f if x.rule_id == "play.fgs_type"]
        self.assertEqual(len(d), 1)
        self.assertIn(".A", d[0])
        for skipped in (".B", ".Tile", "AppLocales", ".Off"):
            self.assertNotIn(skipped, d[0])

    def test_release_signed_with_debug_key(self):
        self.manifest("")
        self.w("app/build.gradle.kts", 'android { buildTypes { release { isMinifyEnabled = true\n'
               '  proguardFiles(getDefaultProguardFile("a.txt"))\n  signingConfig = signingConfigs.getByName("debug") }\n'
               '  debug { } } }')
        _, ids = self.ids("google")
        self.assertIn("play.release_debug_signing", ids)
        self.w("app/build.gradle.kts", 'android { buildTypes { release { signingConfig = signingConfigs.getByName("release") }'
               ' debug { signingConfig = signingConfigs.getByName("debug") } } }')
        _, ids = self.ids("google")
        self.assertNotIn("play.release_debug_signing", ids)      # debug type may use the debug key

    def test_groovy_release_debug_signing(self):
        self.manifest("")
        self.w("app/build.gradle", "android { buildTypes { release { signingConfig signingConfigs.debug } } }")
        _, ids = self.ids("google")
        self.assertIn("play.release_debug_signing", ids)


class IosExtra(Base):
    def icon_set(self, size, dims=None, idiom="ios-marketing"):
        name = "App/Assets.xcassets/AppIcon.appiconset"
        self.w(f"{name}/Contents.json", json.dumps({"images": [{"idiom": idiom, "size": f"{size}x{size}",
                                                                 "filename": "i.png"}]}))
        if dims:
            self.w(f"{name}/i.png", png(*dims))

    def base(self, plist_extra="<key>UILaunchScreen</key><dict/>"):
        self.w("App.xcodeproj/project.pbxproj", "IPHONEOS_DEPLOYMENT_TARGET = 15.0;")
        self.w("App/Info.plist", plist(plist_extra))

    def test_icon_size_checks(self):
        self.base()
        self.icon_set(1024, (1024, 1024))
        _, ids = self.ids("apple")
        self.assertNotIn("apple.app_icon", ids)
        self.icon_set(1024, (512, 512))
        f, ids = self.ids("apple")
        self.assertTrue(any("512x512" in x.detail for x in f if x.rule_id == "apple.app_icon"))
        self.icon_set(60, (60, 60), idiom="iphone")
        f, _ = self.ids("apple")
        self.assertTrue(any("no 1024x1024" in x.detail for x in f if x.rule_id == "apple.app_icon"))

    def test_no_icon_set_at_all_and_icon_composer(self):
        self.base()
        _, ids = self.ids("apple")
        self.assertIn("apple.app_icon", ids)
        self.w("App/AppIcon.icon/icon.json", "{}")
        _, ids = self.ids("apple")
        self.assertNotIn("apple.app_icon", ids)

    def test_mac_icon_set_is_not_an_ios_icon(self):
        self.base()
        self.icon_set(1024, (1024, 1024), idiom="mac")
        f, _ = self.ids("apple")
        self.assertTrue(any("no iOS app icon set" in x.detail for x in f if x.rule_id == "apple.app_icon"))

    def test_launch_screen_ignores_macos_plists(self):
        self.base("")
        self.w("macos/Runner/Info.plist", plist("<key>LSMinimumSystemVersion</key><string>11</string>"))
        f, _ = self.ids("apple")
        where = [x.location for x in f if x.rule_id == "apple.launch_screen"]
        self.assertEqual(where, ["App/Info.plist"])
        self.w("App/Info.plist", plist("<key>UILaunchStoryboardName</key><string>LaunchScreen</string>"))
        _, ids = self.ids("apple")
        self.assertNotIn("apple.launch_screen", ids)

    def test_deployment_target_sources(self):
        self.w("App.xcodeproj/project.pbxproj", "IPHONEOS_DEPLOYMENT_TARGET = 12.0;\nIPHONEOS_DEPLOYMENT_TARGET = 15.0;")
        self.w("Podfile", "platform :ios, '11.0'\n")
        self.w("Package.swift", "platforms: [.iOS(.v12)]")
        f, _ = self.ids("apple")
        found = {x.location for x in f if x.rule_id == "apple.deployment_target"}
        self.assertEqual(found, {"App.xcodeproj/project.pbxproj", "Podfile", "Package.swift"})
        self.w("App.xcodeproj/project.pbxproj", "IPHONEOS_DEPLOYMENT_TARGET = 13.0;")
        self.w("Podfile", "platform :ios, '13.0'\n")
        self.w("Package.swift", "platforms: [.iOS(.v14)]")
        _, ids = self.ids("apple")
        self.assertNotIn("apple.deployment_target", ids)

    def test_xcode_version_in_ci(self):
        self.base()
        self.w(".github/workflows/ios.yml", "steps:\n  - uses: maxim-lobanov/setup-xcode@v1\n    with:\n      xcode-version: '16.2'\n")
        f, _ = self.ids("apple")
        self.assertTrue(any("Xcode 16" in x.detail for x in f if x.rule_id == "apple.xcode_version"))
        self.w(".github/workflows/ios.yml", "xcode-version: latest-stable\nrunner: macos-26\n  DEVELOPER_DIR: /Applications/Xcode_26.0.app\n")
        _, ids = self.ids("apple")
        self.assertNotIn("apple.xcode_version", ids)

    def test_push_entitlement(self):
        self.base()
        self.w("src/push.swift", "UIApplication.shared.registerForRemoteNotifications()")
        _, ids = self.ids("apple")
        self.assertIn("apple.push_entitlement", ids)
        self.w("App/App.entitlements", '<?xml version="1.0"?><plist version="1.0"><dict><key>aps-environment</key>'
                                       '<string>development</string></dict></plist>')
        _, ids = self.ids("apple")
        self.assertNotIn("apple.push_entitlement", ids)

    def test_background_modes(self):
        self.base("<key>UILaunchScreen</key><dict/><key>UIBackgroundModes</key><array><string>audio</string>"
                  "<string>location</string><string>remote-notification</string></array>")
        f, _ = self.ids("apple")
        d = " | ".join(x.detail for x in f if x.rule_id == "apple.background_modes")
        self.assertIn("'audio'", d)
        self.assertIn("'remote-notification'", d)
        self.assertIn("NSLocation", d)
        self.w("src/p.swift", "let p = AVAudioPlayer(); registerForRemoteNotifications()")
        self.base("<key>UILaunchScreen</key><dict/><key>UIBackgroundModes</key><array><string>audio</string>"
                  "<string>remote-notification</string></array>")
        _, ids = self.ids("apple")
        self.assertNotIn("apple.background_modes", ids)


class BothExtra(Base):
    def manifest(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')

    def test_payments_without_iap(self):
        self.manifest()
        self.w("package.json", '{"dependencies": {"@stripe/stripe-react-native": "1"}}')
        _, ids = self.ids()
        self.assertIn("both.payments_iap", ids)
        self.w("package.json", '{"dependencies": {"@stripe/stripe-react-native": "1", "react-native-iap": "1"}}')
        _, ids = self.ids()
        self.assertNotIn("both.payments_iap", ids)

    def test_listing_text_limits(self):
        self.manifest()
        self.w("fastlane/metadata/en-US/name.txt", "N" * 31)
        self.w("fastlane/metadata/en-US/keywords.txt", "é" * 60)             # 120 bytes
        self.w("fastlane/metadata/en-US/subtitle.txt", "ok")
        self.w("fastlane/metadata/android/en-US/title.txt", "T" * 30)
        self.w("fastlane/metadata/android/en-US/short_description.txt", "S" * 81)
        f, _ = self.ids()
        got = {(x.rule_id, Path(x.location).name) for x in f if x.rule_id.startswith("listing.")}
        self.assertEqual(got, {("listing.apple_text_limits", "name.txt"), ("listing.apple_text_limits", "keywords.txt"),
                               ("listing.play_text_limits", "short_description.txt")})

    def test_screenshots(self):
        self.manifest()
        self.w("fastlane/screenshots/en-US/1.png", png(1290, 2796))
        self.w("fastlane/screenshots/en-US/2.png", png(1000, 1000))
        f, _ = self.ids()
        bad = [x.location for x in f if x.rule_id == "listing.apple_screenshots"]
        self.assertEqual(bad, ["fastlane/screenshots/en-US/2.png"])
        self.w("fastlane/metadata/android/en-US/images/phoneScreenshots/1.png", png(1080, 1920))
        f, _ = self.ids()
        self.assertTrue(any(x.rule_id == "listing.play_screenshots" for x in f))
        self.w("fastlane/metadata/android/en-US/images/phoneScreenshots/2.png", png(1080, 1920))
        f, _ = self.ids()
        self.assertFalse(any(x.rule_id == "listing.play_screenshots" for x in f))

    def test_privacy_policy(self):
        self.manifest()
        self.w("package.json", '{"dependencies": {"@sentry/react-native": "8"}}')
        _, ids = self.ids()
        self.assertIn("both.privacy_policy", ids)
        self.w("src/Settings.tsx", "<Link url='https://x.com/privacy-policy'>Privacy policy</Link>")
        _, ids = self.ids()
        self.assertNotIn("both.privacy_policy", ids)
        self.w("fastlane/metadata/en-US/privacy_url.txt", "http://x.com/p")
        f, _ = self.ids()
        self.assertTrue(any("not https" in x.detail for x in f if x.rule_id == "both.privacy_policy"))

    def test_ugc_moderation(self):
        self.manifest()
        self.w("package.json", '{"dependencies": {"stream-chat-react-native": "1"}}')
        _, ids = self.ids()
        self.assertIn("both.ugc_moderation", ids)
        self.w("src/Chat.tsx", "function onReportUser(id) {}  // reportUser\nblock_user(id)")
        _, ids = self.ids()
        self.assertNotIn("both.ugc_moderation", ids)


class RealWorldExtraRegressions(Base):
    """False positives and misses found by running the new checks on real open-source apps."""

    def test_debug_signing_fallback_next_to_a_real_release_config_is_not_flagged(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("android/app/build.gradle", "android { buildTypes { release {\n if (useReleaseKey) {\n"
               " signingConfig signingConfigs.release\n } else {\n signingConfig signingConfigs.debug\n }\n } } }")
        _, ids = self.ids("google")
        self.assertNotIn("play.release_debug_signing", ids)

    def test_ci_scripts_are_not_app_code(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w(".github/workflows/check.js", "await github.rest.issues.createComment({})")
        _, ids = self.ids()
        self.assertNotIn("both.ugc_moderation", ids)

    def test_payment_sdk_name_in_art_or_text_is_not_a_dependency(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("res/drawable/stripe_pattern.xml", "<vector>stripe paypal</vector>")
        self.w("lib/products.dart", "const name = 'Striped sweater, stripe';")
        _, ids = self.ids()
        self.assertNotIn("both.payments_iap", ids)

    def test_commented_out_podfile_platform_is_ignored(self):
        self.w("App.xcodeproj/project.pbxproj", "IPHONEOS_DEPLOYMENT_TARGET = 15.0;")
        self.w("Podfile", "# platform :ios, '11.0'\nplatform :ios, '15.0'\n")
        _, ids = self.ids("apple")
        self.assertNotIn("apple.deployment_target", ids)

    def test_xcode_keys_with_sdk_conditions_are_read(self):
        self.w("App.xcodeproj/project.pbxproj",
               'GENERATE_INFOPLIST_FILE = YES;\n"INFOPLIST_KEY_UILaunchScreen_Generation[sdk=iphoneos*]" = YES;\n')
        self.w("App/Info.plist", plist("<key>UIBackgroundModes</key><array/>"))
        _, ids = self.ids("apple")
        self.assertNotIn("apple.launch_screen", ids)


class RatingHints(Base):
    def test_hints_from_code(self):
        from storecheck import privacy
        from storecheck.discover import discover
        self.w("pubspec.yaml", "dependencies:\n  webview_flutter: 1\n  google_mobile_ads: 2\n  flutter_chat_ui: 1\n")
        d = privacy.build_draft(discover(self.root))
        topics = {r["topic"] for r in d["rating"]}
        self.assertTrue({"Unrestricted Web Access", "Advertising", "Messaging and Chat"} <= topics)
        self.assertIn("Age and content rating hints", privacy.to_markdown(d))

    def test_no_hints_without_evidence(self):
        from storecheck import privacy
        from storecheck.discover import discover
        self.w("main.py", "print('hi')")
        self.assertEqual(privacy.build_draft(discover(self.root))["rating"], [])


class FixPatches(Base):
    """Each patch must apply with git, and applying it must make its finding disappear."""

    def apply_and_rescan(self, store="both"):
        import subprocess
        from storecheck import fixes
        project, findings = scan(str(self.root), store)
        ed, skipped = fixes.build_fixes(project, findings)
        patch = fixes.to_patch(ed)
        self.assertTrue(patch, "expected a patch")
        (self.root.parent / (self.root.name + ".patch")).write_text(patch)
        patch_file = self.root.parent / (self.root.name + ".patch")
        r = subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        subprocess.run(["git", "apply", str(patch_file)], cwd=self.root, check=True)
        patch_file.unlink()
        return findings, scan(str(self.root), store)[1], skipped

    def test_debuggable_target_sdk_and_exported(self):
        self.w("app/src/main/AndroidManifest.xml",
               f'<manifest {NS}><application android:debuggable="true" android:label="x">'
               '<activity android:name=".Main"><intent-filter><category android:name="android.intent.category.LAUNCHER"/>'
               '</intent-filter></activity>'
               '<service android:name=".S"><intent-filter/></service>'
               '<activity android:name=".L" android:exported="false"><intent-filter><category '
               'android:name="android.intent.category.LAUNCHER"/></intent-filter></activity>'
               '</application></manifest>')
        self.w("app/build.gradle", 'apply plugin: "com.android.application"\nandroid { defaultConfig { targetSdk 33 } }')
        before, after, _ = self.apply_and_rescan("google")
        b = {f.rule_id for f in before}
        a = {f.rule_id for f in after}
        self.assertTrue({"play.debuggable", "play.target_sdk", "play.exported_missing"} <= b)
        self.assertEqual(a & {"play.debuggable", "play.target_sdk", "play.exported_missing"}, set())
        text = (self.root / "app/src/main/AndroidManifest.xml").read_text()
        self.assertRegex(text, r'<activity android:exported="true" android:name="\.Main"')
        self.assertRegex(text, r'<service android:exported="false" android:name="\.S"')
        self.assertRegex(text, r'android:name="\.L" android:exported="true"')

    def test_ios_usage_strings_and_deployment_target(self):
        self.w("App.xcodeproj/project.pbxproj", "IPHONEOS_DEPLOYMENT_TARGET = 11.0;\nIPHONEOS_DEPLOYMENT_TARGET = 15.0;\n")
        self.w("Podfile", "platform :ios, '12.0'\n")
        self.w("App/Info.plist", plist("<key>UILaunchScreen</key><dict/>"))
        self.w("src/c.swift", "let d = AVCaptureDevice.default(for: .video)")
        before, after, _ = self.apply_and_rescan("apple")
        self.assertTrue({"apple.usage_strings", "apple.deployment_target"} <= {f.rule_id for f in before})
        self.assertEqual({f.rule_id for f in after} & {"apple.usage_strings", "apple.deployment_target"}, set())
        self.assertIn("TODO", (self.root / "App/Info.plist").read_text())
        self.assertIn("IPHONEOS_DEPLOYMENT_TARGET = 15.0;", (self.root / "App.xcodeproj/project.pbxproj").read_text())

    def test_never_edits_files_and_reports_what_it_skips(self):
        from storecheck import fixes
        self.w("app/src/main/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("app/build.gradle.kts", 'android { buildTypes { release { signingConfig = signingConfigs.getByName("debug") } } }')
        before = (self.root / "app/build.gradle.kts").read_text()
        project, findings = scan(str(self.root), "google")
        ed, skipped = fixes.build_fixes(project, findings)
        self.assertEqual(fixes.to_patch(ed), "")
        self.assertTrue(any("release_debug_signing" in s for s in skipped))
        self.assertEqual((self.root / "app/build.gradle.kts").read_text(), before)

    def test_cli_writes_patch_file(self):
        import contextlib
        import io
        from storecheck.__main__ import main
        self.w("app/src/main/AndroidManifest.xml", f'<manifest {NS}><application android:debuggable="true"/></manifest>')
        out = self.root.parent / (self.root.name + "-out.patch")
        with contextlib.redirect_stdout(io.StringIO()):
            main([str(self.root), "--fix-plan", str(out)])
        self.assertIn("debuggable", out.read_text())
        out.unlink()


class SigningFormatting(Base):
    def test_single_line_gradle_with_release_fallback(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("app/build.gradle", "android{buildTypes{release{ if(k){signingConfig signingConfigs.release}"
                                   "else{signingConfig signingConfigs.debug} }}}")
        _, ids = self.ids("google")
        self.assertNotIn("play.release_debug_signing", ids)

    def test_named_debug_config_is_recognised(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("app/build.gradle.kts", 'android { buildTypes { release { signingConfig = signingConfigs.named("debug").get() } } }')
        _, ids = self.ids("google")
        self.assertIn("play.release_debug_signing", ids)
