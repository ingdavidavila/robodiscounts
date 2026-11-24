import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from storecheck import gui

NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'


class ParseGithub(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(gui.parse_github("https://github.com/o/r"), ("https://github.com/o/r.git", None))
        self.assertEqual(gui.parse_github("https://github.com/o/r.git/"), ("https://github.com/o/r.git", None))
        self.assertEqual(gui.parse_github("https://github.com/o/r/tree/feat/x"),
                         ("https://github.com/o/r.git", "feat/x"))

    def test_rejects(self):
        for bad in ["http://github.com/o/r", "https://evil.com/o/r", "https://github.com/o",
                    "https://github.com/o/r --upload-pack=x", "file:///etc", "https://github.com/o/r/tree/-x",
                    "https://github.com/o/r/tree/a/../b", "ssh://git@github.com/o/r", ""]:
            with self.assertRaises(gui.UserError, msg=bad):
                gui.parse_github(bad)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.url = gui.serve(0)
        cls.base, cls.token = cls.url.split("/?t=")
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp()
        m = Path(cls.tmp) / "app/src/main/AndroidManifest.xml"
        m.parent.mkdir(parents=True)
        m.write_text(f'<manifest {NS}><application android:debuggable="true"/></manifest>')

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, body, token=None, host=None):
        req = urllib.request.Request(self.base + "/api/scan", data=json.dumps(body).encode(),
                                     headers={"X-Token": token or self.token,
                                              **({"Host": host} if host else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_page_needs_token(self):
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(self.base + "/")
        self.assertEqual(c.exception.code, 403)
        with urllib.request.urlopen(self.url) as r:
            html = r.read().decode()
        self.assertIn(self.token, html)
        self.assertNotIn("__TOKEN__", html)

    def test_bad_token_and_host(self):
        self.assertEqual(self.post({}, token="nope")[0], 403)
        self.assertEqual(self.post({}, host="evil.example")[0], 403)

    def test_local_scan(self):
        code, j = self.post({"source": "local", "target": self.tmp})
        self.assertEqual(code, 200)
        self.assertIn("play.debuggable", {f["rule_id"] for f in j["findings"]})
        self.assertIn("privacy", j)

    def test_errors(self):
        self.assertEqual(self.post({"source": "local", "target": "/no/such/dir"})[0], 400)
        self.assertEqual(self.post({"source": "github", "target": "https://evil.com/a/b"})[0], 400)
        self.assertEqual(self.post({"source": "x", "target": "y"})[0], 400)
        self.assertEqual(self.post({"source": "local", "target": self.tmp, "store": "zzz"})[0], 400)

    def test_github_clone_is_used_and_cleaned(self):
        seen = {}

        def fake_clone(url, branch, dest):
            seen["dest"] = dest
            shutil.copytree(self.tmp, dest)
        with mock.patch.object(gui, "clone", fake_clone):
            code, j = self.post({"source": "github", "target": "https://github.com/o/r"})
        self.assertEqual(code, 200)
        self.assertIn("play.debuggable", {f["rule_id"] for f in j["findings"]})
        self.assertFalse(Path(seen["dest"]).exists())

    def test_clone_failure_message(self):
        with mock.patch.object(gui.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=128, stderr="fatal: repository not found\n")
            with self.assertRaises(gui.UserError):
                gui.clone("https://github.com/o/r.git", None, "/tmp/x-nonexistent")


if __name__ == "__main__":
    unittest.main()
