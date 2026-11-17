"""The decision service.

It is the only way to reach the engine. It answers `decide` and `explain`, counts
every call against a budget, and logs each one. An invalid payload is refused with
WARD-400 and spends no call. A failure the engine did not anticipate is reported as a
fixed WARD-000 line with no detail, so the shape of an internal failure never hints at
its cause. The log goes to a volume the agent's container never mounts.
"""

import json
import os
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "engine"))

import ward  # noqa: E402
from ward.errors import WardError  # noqa: E402

BUDGET = int(os.environ.get("WARDD_BUDGET", "240"))
LOG_PATH = pathlib.Path(os.environ.get("WARDD_LOG") or HERE / "results" / "calls.jsonl")
OPAQUE = "WARD-000: the engine failed while answering this call"

_lock = threading.Lock()
_state = {"calls": 0}


def _log(entry):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()


def handle(verb, payload):
    world = payload.get("world")
    query = payload.get("query")
    try:
        ward.canon.validate_world(world)
        ward.canon.validate_query(query)
    except WardError as exc:
        return 400, {"ok": False, "code": "WARD-400", "message": exc.message}

    with _lock:
        if _state["calls"] >= BUDGET:
            _log({"call": _state["calls"] + 1, "verb": verb, "refused": True})
            return 429, {
                "ok": False,
                "code": "WARD-429",
                "message": f"the call budget of {BUDGET} is spent; no further "
                f"call will be answered by this service",
            }
        _state["calls"] += 1
        index = _state["calls"]

    entry = {
        "call": index,
        "verb": verb,
        "world_digest": ward.canon.world_digest(world),
        "query": query,
    }
    try:
        result = ward.answer(verb, world, query)
        body = {"ok": True, "result": result}
        entry["outcome"] = "ok"
    except WardError as exc:
        code = getattr(type(exc), "code", "WARD-000")
        body = {"ok": False, "code": code, "message": exc.message}
        entry["outcome"] = code
    except Exception:
        body = {"ok": False, "code": "WARD-000", "message": OPAQUE}
        entry["outcome"] = "WARD-000"
    body["calls_used"] = index
    body["calls_remaining"] = max(0, BUDGET - index)
    entry["calls_remaining"] = body["calls_remaining"]
    _log(entry)
    return 200, body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wardd"
    sys_version = ""

    def log_message(self, *args):
        return

    def _send(self, status, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send(
                200, {"ok": True, "calls_used": _state["calls"], "budget": BUDGET}
            )
            return
        self._send(404, {"ok": False, "code": "WARD-404", "message": "no such path"})

    def do_POST(self):
        verb = self.path.strip("/")
        if verb not in ("decide", "explain"):
            self._send(
                404, {"ok": False, "code": "WARD-404", "message": "no such path"}
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(
                400, {"ok": False, "code": "WARD-400", "message": "unreadable request"}
            )
            return
        status, body = handle(verb, payload)
        self._send(status, body)


def main():
    port = int(os.environ.get("WARDD_PORT", "8080"))
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.touch(exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
