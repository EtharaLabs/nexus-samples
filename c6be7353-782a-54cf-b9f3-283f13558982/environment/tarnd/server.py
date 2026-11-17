"""The query service.

It is the only way to reach the engine. It answers two calls, returns rows, plan
text or a TARN code, counts every call against a budget, and logs each one. An
unexpected failure inside the engine is reported as a fixed TARN-000 line: no
traceback, no module name, no line number ever leaves this process.
"""

import json
import os
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/srv/engine")

import dbshape  # noqa: E402
import tarn  # noqa: E402
from tarn.types import TarnError  # noqa: E402

BUDGET = int(os.environ.get("TARND_BUDGET", "250"))
LOG_PATH = pathlib.Path(os.environ.get("TARND_LOG", "/results/calls.jsonl"))
OPAQUE = "TARN-000: the engine failed while answering this statement"

_lock = threading.Lock()
_state = {"calls": 0}


def _log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()


def _digest(database) -> str:
    return dbshape.digest(database)


def _answer(verb: str, database, sql: str) -> dict:
    conn = tarn.connect(database)
    if verb == "explain":
        return {
            "ok": True,
            "plan": conn.explain(sql),
            "rows_processed": conn.stats.rows_processed,
        }
    result = conn.execute(sql)
    return {
        "ok": True,
        "columns": result.columns,
        "rows": result.rows,
        "rows_processed": conn.stats.rows_processed,
    }


def handle(verb: str, payload: dict) -> tuple:
    database = payload.get("database")
    sql = payload.get("sql")
    if not isinstance(sql, str) or database is None:
        return 400, {
            "ok": False,
            "code": "TARN-400",
            "message": "a call needs a database and a sql string",
        }
    problem = dbshape.problem(database)
    if problem is not None:
        return 400, {
            "ok": False,
            "code": "TARN-400",
            "message": f"the database is not valid: {problem}; no call was spent",
        }

    with _lock:
        if _state["calls"] >= BUDGET:
            _log({"call": _state["calls"] + 1, "verb": verb, "refused": True})
            return 429, {
                "ok": False,
                "code": "TARN-429",
                "message": f"the call budget of {BUDGET} is spent; no further "
                f"call will be answered by this service",
            }
        _state["calls"] += 1
        index = _state["calls"]

    entry = {"call": index, "verb": verb, "database": _digest(database), "sql": sql}
    try:
        body = _answer(verb, database, sql)
        entry["outcome"] = "ok"
    except TarnError as exc:
        code = getattr(type(exc), "code", "TARN-000")
        body = {"ok": False, "code": code, "message": str(exc)}
        entry["outcome"] = code
    except RecursionError:
        body = {"ok": False, "code": "TARN-000", "message": OPAQUE}
        entry["outcome"] = "TARN-000"
    except Exception:
        # Anything the engine did not anticipate is reported the same opaque way, so
        # the shape of an internal failure never hints at its cause.
        body = {"ok": False, "code": "TARN-000", "message": OPAQUE}
        entry["outcome"] = "TARN-000"
    body["calls_used"] = index
    body["calls_remaining"] = max(0, BUDGET - index)
    entry["calls_remaining"] = body["calls_remaining"]
    _log(entry)
    return 200, body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tarnd"
    sys_version = ""

    def log_message(self, *args) -> None:
        return

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(
                200, {"ok": True, "calls_used": _state["calls"], "budget": BUDGET}
            )
            return
        self._send(404, {"ok": False, "code": "TARN-404", "message": "no such path"})

    def do_POST(self) -> None:
        verb = self.path.strip("/")
        if verb not in ("execute", "explain"):
            self._send(
                404, {"ok": False, "code": "TARN-404", "message": "no such path"}
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(
                400, {"ok": False, "code": "TARN-400", "message": "unreadable request"}
            )
            return
        status, body = handle(verb, payload)
        self._send(status, body)


def main() -> int:
    port = int(os.environ.get("TARND_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
