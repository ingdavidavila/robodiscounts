"""Local web GUI for storecheck.  Run:  python -m storecheck.gui

Serves a single page on 127.0.0.1 only. Scans either a local folder/archive or a
GitHub repository (shallow-cloned into a temp dir that is deleted afterwards).
Standard library only. Everything shown comes from untrusted project files, so the
page builds its DOM with textContent and never injects HTML.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import llm, privacy
from .engine import scan

GITHUB_RX = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/([A-Za-z0-9_./-]+))?/?$")
CLONE_TIMEOUT = 240
MAX_BODY = 64 * 1024
PAGE = (Path(__file__).parent / "gui_page.html").read_text(encoding="utf-8") \
    if (Path(__file__).parent / "gui_page.html").exists() else ""


class UserError(Exception):
    """Problem the user can fix; message is safe to show."""


def parse_github(url: str) -> tuple[str, str | None]:
    m = GITHUB_RX.match(url.strip())
    if not m:
        raise UserError("Enter a GitHub link like https://github.com/owner/repo "
                        "(optionally .../tree/branch).")
    owner, repo, branch = m.group(1), m.group(2), m.group(3)
    if branch and (branch.startswith("-") or ".." in branch):
        raise UserError("Unsupported branch name.")
    return f"https://github.com/{owner}/{repo}.git", branch


def clone(url: str, branch: str | None, dest: str) -> None:
    cmd = ["git", "-c", "core.symlinks=false", "-c", "protocol.file.allow=never",
           "clone", "--depth", "1", "--single-branch", "--no-tags", "--quiet"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", url, dest]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=env)
    except FileNotFoundError:
        raise UserError("git is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        raise UserError(f"Cloning took longer than {CLONE_TIMEOUT}s; try a smaller repo or a local folder.")
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise UserError("Could not clone (private repo needs git credentials on this machine, "
                        f"or the branch/name is wrong): {tail[0][:200]}")


def run_scan(req: dict) -> dict:
    source = req.get("source")
    target = (req.get("target") or "").strip()
    store = req.get("store", "both")
    if store not in ("both", "google", "apple"):
        raise UserError("Unknown store.")
    if not target:
        raise UserError("Enter a GitHub link or a folder path.")
    tmp = None
    try:
        if source == "github":
            url, branch = parse_github(target)
            tmp = tempfile.mkdtemp(prefix="storecheck-")
            path = os.path.join(tmp, "repo")
            clone(url, branch, path)
        elif source == "local":
            path = os.path.expanduser(target)
            if not os.path.exists(path):
                raise UserError(f"Path not found on this machine: {target}")
        else:
            raise UserError("Unknown source.")
        project, findings = scan(path, store)
        draft = privacy.build_draft(project)
        from dataclasses import asdict
        out = {
            "platforms": [n for n, on in (("android", project.has_android), ("ios", project.has_ios)) if on],
            "frameworks": sorted(project.frameworks),
            "notes": project.notes,
            "passed": [{"rule_id": i, "title": t} for i, t in getattr(project, "passed", [])],
            "findings": [asdict(f) for f in findings],
            "privacy": draft,
            "privacy_markdown": privacy.to_markdown(draft),
        }
        if req.get("explain"):
            url_ = req.get("llm_url") or "http://localhost:11434/v1"
            model = req.get("model") or "qwen2.5-coder:14b"
            out["ai_findings"] = llm.explain(findings, url_, model)
            out["ai_privacy"] = llm.privacy_policy_text(draft, url_, model)
        return out
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def make_handler(token: str, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                             "connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            u = urlparse(self.path)
            if not self._host_ok() or u.path != "/" or \
                    not secrets.compare_digest(parse_qs(u.query).get("t", [""])[0], token):
                return self._send(403, b"Forbidden. Open the URL printed by storecheck.gui.", "text/plain")
            self._send(200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8")

        def do_POST(self):
            if not self._host_ok() or self.path != "/api/scan" or \
                    not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                return self._send(403, b'{"error":"forbidden"}', "application/json")
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > MAX_BODY:
                    raise UserError("Request too large.")
                req = json.loads(self.rfile.read(n) or b"{}")
                result = run_scan(req)
                self._send(200, json.dumps(result).encode(), "application/json")
            except UserError as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            except (ValueError, KeyError):
                self._send(400, b'{"error":"bad request"}', "application/json")
            except Exception as e:  # keep the server alive
                self._send(500, json.dumps({"error": f"scan failed: {type(e).__name__}"}).encode(),
                           "application/json")

    return H


def serve(port: int = 0, open_browser: bool = True):
    token = secrets.token_urlsafe(16)
    srv = ThreadingHTTPServer(("127.0.0.1", port), lambda *a, **k: None)
    real_port = srv.server_address[1]
    srv.RequestHandlerClass = make_handler(token, real_port)
    url = f"http://127.0.0.1:{real_port}/?t={token}"
    return srv, url


def main(argv=None):
    ap = argparse.ArgumentParser(prog="storecheck.gui", description="Local web GUI for storecheck.")
    ap.add_argument("--port", type=int, default=0, help="port (default: random free port)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    srv, url = serve(a.port)
    print(f"storecheck GUI: {url}\n(only reachable from this machine; Ctrl+C to stop)")
    if not a.no_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
