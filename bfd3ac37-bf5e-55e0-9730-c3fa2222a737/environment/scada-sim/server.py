"""SCADA sidecar: one trial seed from the pre-admitted pool, then the paced plant behind the API.

Before it answers any request the sidecar draws the trial seed from seeds.json, a list of seeds
admitted at build time, with a secure random choice. Grader-only state (seed, action log, request
log) is written to /var/scada/private, which no other container mounts. Readiness is a file, so
the compose health check never starts plant time. Every request is logged in served order, routed
or not, one line each; logging never changes a response.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, "/opt/scada")

from plantsim.openapi import SPEC  # noqa: E402
from plantsim.session import ROUTES, ApiError, Session  # noqa: E402

PRIVATE = Path(os.environ.get("SCADA_PRIVATE", "/var/scada/private"))
READY = Path(os.environ.get("SCADA_READY", "/var/scada/ready"))
POOL = Path(os.environ.get("SCADA_POOL", "/opt/scada/seeds.json"))
PORT = 8080
KEEP = 2048  # characters of a request target or an unparsed body kept in the log


def _write_private(name: str, data) -> None:
    path = PRIVATE / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class PrivateLog:
    """The session's sink: request records and newly served table rows are appended one JSON line
    each (rows before the record that first names them); the action log is rewritten whole."""

    def __init__(self, private: Path):
        self.requests = open(private / "requests.jsonl", "a", encoding="utf-8")
        self.tables = open(private / "tables.jsonl", "a", encoding="utf-8")
        for f in (self.requests, self.tables):
            os.chmod(f.name, 0o600)

    @staticmethod
    def _line(f, obj) -> None:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")
        f.flush()

    def request(self, record: dict) -> None:
        self._line(self.requests, record)

    def rows(self, table: str, rows: list) -> None:
        for i, row in rows:
            self._line(self.tables, {"table": table, "i": i, "row": row})

    def action_log(self, log: dict) -> None:
        _write_private("action_log.json", log)


def draw_seed() -> int:
    """One seed from the pre-admitted pool, chosen with a secure random choice."""
    pool = json.loads(POOL.read_text())
    if (
        not isinstance(pool, list)
        or not pool
        or not all(isinstance(s, int) and not isinstance(s, bool) for s in pool)
    ):
        raise SystemExit("the seed pool must be a non-empty list of integers")
    return secrets.choice(pool)


def _query(target: str) -> dict:
    return {k: v[-1] for k, v in parse_qs(urlparse(target).query).items()}


class Handler(BaseHTTPRequestHandler):
    server_version = "scada/4.2"
    sys_version = ""
    session: Session

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
        request = {
            "method": method,
            "path": url.path,
            "target": self.path[:KEEP],
            "query": _query(self.path),
            "body": None,
        }
        if method == "GET" and url.path == "/api/v1/openapi.json":
            self.session.log_unrouted(request, 200, None, SPEC)
            self._send(200, SPEC)
            return
        op = ROUTES.get((method, url.path))
        if op is None:
            self.session.log_unrouted(request, 404, "not found", {"error": "not found"})
            self._send(404, {"error": "not found"})
            return
        params: dict = dict(request["query"])
        if method == "POST":
            data = b""
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                data = self.rfile.read(length)
                params = json.loads(data or b"{}")
                if not isinstance(params, dict):
                    raise ValueError
            except ValueError:
                request["body"] = data.decode(errors="replace")[:KEEP]
                message = "the body must be a JSON object"
                self.session.log_unrouted(request, 400, message, {"error": message})
                self._send(400, {"error": message})
                return
            except Exception as exc:  # no response is served; the record says so
                request["body"] = data.decode(errors="replace")[:KEEP]
                self.session.log_unrouted(
                    request, None, f"no response ({type(exc).__name__})", None
                )
                raise
            request["body"] = params
        try:
            result = self.session.call(op, params, request)
        except ApiError as exc:
            self._send(exc.status, {"error": exc.message})
            return
        self._send(200, result)

    def send_error(self, code, message=None, explain=None):
        """Log a request refused before routing (an unsupported method such as HEAD or OPTIONS,
        a malformed request line), then answer it exactly as http.server does."""
        try:
            target = getattr(self, "path", None)
            if not isinstance(target, str):
                target = self.requestline if isinstance(self.requestline, str) else ""
            command = self.command if isinstance(self.command, str) and self.command else None
            request = {
                "method": command,
                "path": urlparse(target).path if command else None,
                "target": target[:KEEP],
                "query": _query(target) if command else {},
                "body": None,
            }
            status = int(code)
            text = message or HTTPStatus(status).phrase
            self.session.log_unrouted(request, status, text, None)
        except Exception:  # noqa: BLE001 - logging must never change the answer
            pass
        super().send_error(code, message, explain)

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


def main() -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    seed = draw_seed()
    _write_private("seed.json", {"seed": seed})
    log = PrivateLog(PRIVATE)
    Handler.session = Session(seed, paced=True, sink=log)
    log.action_log(Handler.session.action_log())
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    READY.write_text("ready\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
