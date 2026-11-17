"""Simulator sidecar: one trial seed from the pre-admitted pool, then the paced plant behind the API.

Before it answers any request the sidecar draws the trial seed from the seed pool, a list of seeds
admitted at build time, with a secure random choice. Grader-only state (seed, action log, request
log) is written to the private directory, which no other container mounts. Readiness is a file, so
the compose health check never starts plant time.

Run as ``python3 -m plantops.server`` with the member package importable; the member module
(PLANTOPS_MEMBER, default ``plantsim.member``) names the routes, the OpenAPI document, and the paths.
"""

from __future__ import annotations

import importlib
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .session import ApiError, Session

BASE_ROUTES = {
    ("GET", "/api/v1/status"): "status",
    ("GET", "/api/v1/telemetry"): "telemetry",
    ("GET", "/api/v1/events"): "events",
    ("GET", "/api/v1/raw"): "raw",
    ("POST", "/api/v1/control"): "control",
}
PORT = 8080


def load_member():
    return importlib.import_module(os.environ.get("PLANTOPS_MEMBER", "plantsim.member"))


def private_dir(member) -> Path:
    return Path(os.environ.get("PLANTOPS_PRIVATE", member.PRIVATE_DIR))


def _write_private(root: Path, name: str, data) -> None:
    path = root / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def draw_seed(pool_path: Path) -> int:
    """One seed from the pre-admitted pool, chosen with a secure random choice."""
    pool = json.loads(pool_path.read_text())
    if (
        not isinstance(pool, list)
        or not pool
        or not all(isinstance(s, int) and not isinstance(s, bool) for s in pool)
    ):
        raise SystemExit("the seed pool must be a non-empty list of integers")
    return secrets.choice(pool)


class Handler(BaseHTTPRequestHandler):
    sys_version = ""
    session: Session
    routes: dict
    spec: dict
    private: Path
    log_lock = threading.Lock()

    def log_message(self, format, *args):  # noqa: A002 - quiet: the request log is the record
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str) -> None:
        url = urlparse(self.path)
        if method == "GET" and url.path == "/api/v1/openapi.json":
            self._record(method, url.path, {}, 200)
            self._send(200, self.spec)
            return
        op = self.routes.get((method, url.path))
        if op is None:
            self._record(
                method, url.path, {"request_line": self.requestline[:200]}, 404
            )
            self._send(404, {"error": "not found"})
            return
        params: dict = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if method == "POST":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                params = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(params, dict):
                    raise ValueError
            except ValueError:
                self._record(method, url.path, {}, 400)
                self._send(400, {"error": "the body must be a JSON object"})
                return
        try:
            result = self.session.call(op, params)
        except ApiError as exc:
            self._persist()
            self._send(exc.status, {"error": exc.message})
            return
        self._persist()
        self._send(200, result)

    def _record(self, method: str, path: str, params: dict, status: int) -> None:
        with self.log_lock:
            self.session.requests.append(
                {
                    "step": self.session.now_step(),
                    "op": "unrouted",
                    "method": method,
                    "path": path,
                    "params": params,
                    "status": status,
                }
            )
        self._persist()

    def _persist(self) -> None:
        with self.log_lock:
            persist(self.private, self.session)

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")

    def do_PUT(self):  # noqa: N802
        self._handle("PUT")

    def do_DELETE(self):  # noqa: N802
        self._handle("DELETE")

    def do_PATCH(self):  # noqa: N802
        self._handle("PATCH")


def persist(root: Path, session: Session) -> None:
    _write_private(root, "action_log.json", session.action_log())
    _write_private(root, "requests.json", session.requests)


def main() -> None:
    member = load_member()
    private = private_dir(member)
    private.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    seed = draw_seed(Path(os.environ.get("PLANTOPS_POOL", member.POOL_PATH)))
    _write_private(private, "seed.json", {"seed": seed})
    Handler.session = Session(member, seed, paced=True)
    Handler.routes = {**BASE_ROUTES, **member.EXTRA_ROUTES}
    Handler.spec = member.SPEC
    Handler.private = private
    Handler.server_version = member.SERVER_VERSION
    persist(private, Handler.session)
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    Path(os.environ.get("PLANTOPS_READY", member.READY_PATH)).write_text("ready\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
