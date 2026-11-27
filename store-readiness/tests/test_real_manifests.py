"""Decoders checked against real, tool-built manifests (google/bundletool test data) with independent references."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from storecheck import axml, pbxml
from storecheck.engine import scan

D = Path(__file__).parent / "data" / "real"


def flat(el, out=None):
    out = [] if out is None else out
    out.append([el.tag, sorted([k, "@" if v.startswith("@") else v] for k, v in el.attrib.items())])
    for c in el:
        flat(c, out)
    return out


class RealManifests(unittest.TestCase):
    def test_aab_manifests_match_the_official_schema_decoder(self):
        for name in ("aab_install_time_base", "aab_watchface_base"):
            expected = json.loads((D / f"{name}.expected.json").read_text(encoding="utf-8"))["elements"]
            got = flat(pbxml.decode_proto_manifest((D / f"{name}.pb").read_bytes()))
            self.assertEqual(got, expected, name)

    def test_apk_manifest_matches_androguard(self):
        expected = json.loads((D / "apk_test_app.expected.json").read_text(encoding="utf-8"))["elements"]
        got = flat(axml.decode_axml((D / "apk_test_app.axml").read_bytes()))
        self.assertEqual(got, expected)

    def test_truncated_and_garbage_input_raises_cleanly(self):
        data = (D / "aab_install_time_base.pb").read_bytes()
        for bad in (data[:40], b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff", b""):
            with self.assertRaises(pbxml.PbxmlError):
                pbxml.decode_proto_manifest(bad)

    def _zip(self, path, entries):
        with zipfile.ZipFile(path, "w") as z:
            for n, b in entries.items():
                z.writestr(n, b)

    def test_scan_reads_manifests_inside_an_aab(self):
        with tempfile.TemporaryDirectory() as d:
            aab = Path(d) / "app.aab"
            self._zip(aab, {"base/manifest/AndroidManifest.xml": (D / "aab_install_time_base.pb").read_bytes()})
            project, findings = scan(str(aab), "google")
            self.assertEqual(len(project.archive_manifests), 1)
            self.assertIn("play.target_sdk", {f.rule_id for f in findings})   # targetSdkVersion 28 in the real manifest
            self.assertFalse(any("not decoded" in n for n in project.notes))

    def test_missing_target_sdk_defaults_to_min_sdk_and_modules_are_not_repeated(self):
        from storecheck.checks import _target_sdk_values
        with tempfile.TemporaryDirectory() as d:
            aab = Path(d) / "app.aab"
            pb = (D / "aab_install_time_base.pb").read_bytes()
            self._zip(aab, {"base/manifest/AndroidManifest.xml": pb, "feature/manifest/AndroidManifest.xml": pb})
            project, findings = scan(str(aab), "google")
            self.assertEqual(sum(1 for f in findings if f.rule_id == "play.target_sdk"), 1)
            wf = Path(d) / "wf.aab"
            self._zip(wf, {"base/manifest/AndroidManifest.xml": (D / "aab_watchface_base.pb").read_bytes()})
            project, _ = scan(str(wf), "google")
            self.assertEqual([v for _, v in _target_sdk_values(project)], [30])      # no target: equals minSdk 30
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "a.apk"
            self._zip(apk, {"AndroidManifest.xml": (D / "apk_test_app.axml").read_bytes()})
            project, findings = scan(str(apk), "google")
            self.assertEqual([v for _, v in _target_sdk_values(project)], [1])       # no uses-sdk target, minSdk 1
            self.assertNotIn("play.exported_missing", {f.rule_id for f in findings})  # exported only applies to Android 12+

    def test_scan_reads_the_manifest_inside_an_apk(self):
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "app.apk"
            self._zip(apk, {"AndroidManifest.xml": (D / "apk_test_app.axml").read_bytes()})
            project, findings = scan(str(apk), "google")
            self.assertEqual(len(project.archive_manifests), 1)
            self.assertIn("play.aab", {f.rule_id for f in findings})           # APK supplied, no AAB

    def test_a_broken_bundle_manifest_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as d:
            aab = Path(d) / "app.aab"
            self._zip(aab, {"base/manifest/AndroidManifest.xml": b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"})
            project, _ = scan(str(aab), "google")
            self.assertTrue(any("could not decode" in n for n in project.notes), project.notes)


if __name__ == "__main__":
    unittest.main()
