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
        self.w("app/build.gradle", "android { defaultConfig { targetSdk 31 } }")
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
