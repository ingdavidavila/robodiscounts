import json
import struct
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from storecheck import llm
from storecheck.engine import scan, to_json

NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'


def elf(align):
    ident = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
    hdr = ident + struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    ph = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, 0, 0, align)
    return hdr + ph


def plist(extra=""):
    return ('<?xml version="1.0"?><plist version="1.0"><dict>'
            '<key>CFBundleIdentifier</key><string>com.x.app</string>' + extra +
            '</dict></plist>')


def ids(findings):
    return {f.rule_id for f in findings}


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def w(self, rel, text, mode="w"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text) if mode == "w" else p.write_bytes(text)
        return p

    def test_android_manifest_and_gradle(self):
        self.w("app/src/main/AndroidManifest.xml",
               f'<manifest {NS}><uses-permission android:name="android.permission.READ_SMS"/>'
               '<application android:debuggable="true" android:usesCleartextTraffic="true"/></manifest>')
        self.w("app/build.gradle", 'android { defaultConfig { applicationId "x"\n targetSdk 33 } }')
        _, f = scan(str(self.root))
        self.assertTrue({"play.debuggable", "play.sensitive_permissions", "play.cleartext",
                         "play.target_sdk"} <= ids(f))

    def test_debug_manifest_ignored(self):
        self.w("app/src/debug/AndroidManifest.xml",
               f'<manifest {NS}><application android:debuggable="true"/></manifest>')
        self.w("app/src/main/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        _, f = scan(str(self.root))
        self.assertNotIn("play.debuggable", ids(f))

    def test_ios_signals_work_in_any_language(self):
        self.w("ios/Runner/Info.plist", plist())
        # Dart, Rust and Go sources: the scanner only looks at text
        self.w("lib/main.dart", "import 'package:camera/camera.dart';")
        self.w("src/loc.rs", "// uses CLLocationManager via FFI")
        self.w("pubspec.yaml", "dependencies:\n  google_sign_in: ^6\n  firebase: 1\n")
        _, f = scan(str(self.root), "apple")
        detail = " ".join(x.detail for x in f if x.rule_id == "apple.usage_strings")
        self.assertIn("NSCameraUsageDescription", detail)
        self.assertIn("NSLocationWhenInUseUsageDescription", detail)
        self.assertIn("apple.sign_in_with_apple", ids(f))
        self.assertIn("apple.privacy_manifest", ids(f))

    def test_ios_clean(self):
        self.w("App/Info.plist", plist(
            "<key>CFBundleShortVersionString</key><string>1</string>"
            "<key>CFBundleVersion</key><string>1</string>"
            "<key>ITSAppUsesNonExemptEncryption</key><false/>"))
        self.w("App/PrivacyInfo.xcprivacy", "<plist/>")
        _, f = scan(str(self.root), "apple")
        self.assertEqual(ids(f), set())

    def test_ats_and_missing_keys(self):
        self.w("App/Info.plist", plist(
            "<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>"))
        _, f = scan(str(self.root), "apple")
        self.assertTrue({"apple.ats", "apple.version_keys", "apple.export_compliance"} <= ids(f))

    def test_extension_plist_ignored(self):
        self.w("Ext/Info.plist", plist("<key>NSExtension</key><dict/>"))
        project, _ = scan(str(self.root))
        self.assertFalse(project.has_ios)

    def test_16kb_alignment_in_dir_and_apk(self):
        self.w("jniLibs/arm64-v8a/liba.so", elf(0x1000), "wb")
        self.w("app/src/main/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        _, f = scan(str(self.root), "google")
        self.assertIn("play.16kb", ids(f))
        self.w("jniLibs/arm64-v8a/liba.so", elf(0x4000), "wb")
        _, f = scan(str(self.root), "google")
        self.assertNotIn("play.16kb", ids(f))
        apk = self.root / "x.apk"
        with zipfile.ZipFile(apk, "w") as z:
            z.writestr("lib/arm64-v8a/libb.so", elf(0x1000))
        _, f = scan(str(apk), "google")
        self.assertTrue({"play.16kb", "play.aab"} <= ids(f))

    def test_ipa(self):
        ipa = self.root / "a.ipa"
        with zipfile.ZipFile(ipa, "w") as z:
            z.writestr("Payload/A.app/Info.plist", plist())
        project, f = scan(str(ipa), "apple")
        self.assertTrue(project.has_ios)
        self.assertIn("apple.privacy_manifest", ids(f))

    def test_json_and_empty(self):
        project, f = scan(str(self.root))
        self.assertEqual(json.loads(to_json(project, f))["findings"], [])

    def test_llm_mock_and_failure(self):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"choices": [{"message": {"content": "explained"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.w("App/Info.plist", plist())
        _, f = scan(str(self.root), "apple")
        self.assertEqual(llm.explain(f, f"http://127.0.0.1:{srv.server_port}/v1"), "explained")
        srv.shutdown()
        self.assertIn("unavailable", llm.explain(f, "http://127.0.0.1:1/v1", timeout=2))


if __name__ == "__main__":
    unittest.main()


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def w(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_draft_from_sdks_permissions_and_plist(self):
        from storecheck import privacy
        from storecheck.discover import discover
        self.w("pubspec.yaml", "dependencies:\n  firebase_analytics: 1\n  google_mobile_ads: 2\n")
        self.w("android/app/src/main/AndroidManifest.xml",
               f'<manifest {NS}><uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>'
               '<uses-permission android:name="android.permission.CAMERA"/><application/></manifest>')
        self.w("ios/Runner/Info.plist", plist("<key>NSContactsUsageDescription</key><string>x</string>"
                                                "<key>NSUserTrackingUsageDescription</key><string>x</string>"))
        d = privacy.build_draft(discover(self.root))
        rows = {r["key"]: r for r in d["rows"]}
        self.assertIn("likely", rows["app_interactions"]["strength"])
        self.assertIn("possible", rows["approx_location"]["strength"] + rows["contacts"]["strength"])
        self.assertEqual(rows["contacts"]["apple_category"], "Contacts")
        self.assertIn("Google AdMob / Mobile Ads", d["tracking_signals"])
        self.assertTrue(d["tracking_signals"])
        md = privacy.to_markdown(d)
        self.assertIn("What only you can answer", md)
        self.assertIn("NOT verified", md)

    def test_empty_and_removed_permission(self):
        from storecheck import privacy
        from storecheck.discover import discover
        self.w("android/AndroidManifest.xml",
               f'<manifest {NS} xmlns:tools="http://schemas.android.com/tools">'
               '<uses-permission android:name="android.permission.CAMERA" tools:node="remove"/>'
               '<application/></manifest>')
        d = privacy.build_draft(discover(self.root))
        self.assertEqual(d["rows"], [])
        self.assertIn("No data-collection evidence", privacy.to_markdown(d))

    def test_cli_privacy_draft(self):
        import contextlib
        import io
        from storecheck.__main__ import main
        self.w("package.json", '{"dependencies": {"@sentry/react-native": "1"}}')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([str(self.root), "--privacy-draft", "--format", "json"])
        self.assertEqual(rc, 0)
        keys = {r["key"] for r in json.loads(buf.getvalue())["rows"]}
        self.assertTrue({"crash_logs", "diagnostics"} <= keys)


class RealWorldRegressions(unittest.TestCase):
    """Each case comes from a false positive or silent miss seen when scanning real open-source apps."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def w(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_signals_in_test_mocks_docs_and_lockfiles_are_ignored(self):
        self.w("App/Info.plist", plist())
        self.w("AppUnitTests/MockCLLocationManager.swift", "class MockCLLocationManager: CLLocationManager {}")
        self.w("Sources/FooTests.swift", "let m = CLLocationManager()")
        self.w("README.md", "sign_up flow, createUser( here, AVCaptureDevice")
        self.w("pubspec.lock", "  image_picker:\n    dependency: transitive\n")
        _, f = scan(str(self.root), "apple")
        self.assertNotIn("apple.usage_strings", ids(f))
        self.assertNotIn("apple.account_deletion", ids(f))

    def test_pubspec_yaml_is_not_a_test_file(self):
        self.w("App/Info.plist", plist())
        self.w("pubspec.yaml", "dependencies:\n  google_sign_in: 1\n")
        _, f = scan(str(self.root), "apple")
        self.assertIn("apple.sign_in_with_apple", ids(f))

    def test_framework_and_test_bundle_plists_are_not_apps(self):
        self.w("Fw/Info.plist", plist("<key>CFBundlePackageType</key><string>FMWK</string>"))
        self.w("Bundle/Info.plist", plist("<key>CFBundlePackageType</key><string>BNDL</string>"))
        project, f = scan(str(self.root), "apple")
        self.assertFalse(project.has_ios)
        self.assertEqual(ids(f), set())

    def test_image_picker_alone_is_not_camera_use(self):
        self.w("App/Info.plist", plist())
        self.w("pubspec.yaml", "dependencies:\n  image_picker: 1\n")
        _, f = scan(str(self.root), "apple")
        self.assertNotIn("apple.usage_strings", ids(f))
        self.w("lib/a.dart", "picker.pickImage(source: ImageSource.camera);")
        _, f = scan(str(self.root), "apple")
        self.assertIn("apple.usage_strings", ids(f))

    def test_target_sdk_found_in_variables_gradle_and_kotlin_build_logic(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("android/variables.gradle", "ext { targetSdkVersion = 33 }")
        _, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk", ids(f))
        self.assertNotIn("play.target_sdk_unknown", ids(f))
        self.w("android/variables.gradle", "ext { targetSdkVersion = 36 }")
        self.w("build-logic/convention/src/main/kotlin/P.kt", "defaultConfig.targetSdk = 30")
        _, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk", ids(f))

    def test_library_module_and_fallback_default_do_not_trigger(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("android/app/build.gradle", 'apply plugin: "com.android.application"\nandroid { defaultConfig { targetSdk 36 } }')
        self.w("libs/mod/android/build.gradle", "apply plugin: 'com.android.library'\ntargetSdkVersion safeExtGet('targetSdkVersion', 34)\ntargetSdk 30")
        _, f = scan(str(self.root), "google")
        self.assertNotIn("play.target_sdk", ids(f))

    def test_target_sdk_unknown_is_reported_and_passed_list_exists(self):
        self.w("android/app/build.gradle", "targetSdkVersion flutter.targetSdkVersion")
        project, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk_unknown", ids(f))
        self.w("android/variables.gradle", "ext { targetSdkVersion = 36 }")
        project, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk", {i for i, _ in project.passed})

    def test_root_build_gradle_ext_and_agp_block_syntax(self):
        self.w("android/AndroidManifest.xml", f'<manifest {NS}><application/></manifest>')
        self.w("android/build.gradle", "buildscript { ext { targetSdkVersion = 33 } }")
        _, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk", ids(f))
        self.w("android/build.gradle", "buildscript { ext { targetSdkVersion = 36 } }")
        self.w("app/build.gradle.kts", "defaultConfig {\n targetSdk {\n version = release(MY_TARGET)\n }\n}")
        self.w("gradle.properties", "MY_TARGET=34\n")
        _, f = scan(str(self.root), "google")
        self.assertIn("play.target_sdk", ids(f))
        self.w("gradle.properties", "MY_TARGET=36\n")
        _, f = scan(str(self.root), "google")
        self.assertNotIn("play.target_sdk", ids(f))

    def test_signup_word_in_a_reserved_list_is_not_account_creation(self):
        self.w("App/Info.plist", plist())
        self.w("app/links.ts", "const reservedWords = ['login', 'signup', 'admin_console'];")
        _, f = scan(str(self.root), "apple")
        self.assertNotIn("apple.account_deletion", ids(f))
        self.w("app/routes.ts", "{ path: 'signup', component: SignupPage }")
        _, f = scan(str(self.root), "apple")
        self.assertNotIn("apple.account_deletion", ids(f))  # a route name is not a call
        self.w("app/auth.ts", "await auth.signUp(email, pw);")
        _, f = scan(str(self.root), "apple")
        self.assertIn("apple.account_deletion", ids(f))
