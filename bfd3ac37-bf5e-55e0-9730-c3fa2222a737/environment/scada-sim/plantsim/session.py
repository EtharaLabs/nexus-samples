"""One trial's SCADA session: the plant clock, the API operations, and the grader-only logs.

Plant time starts at the first API call. In paced mode one plant hour takes 150 wall-clock
seconds; in virtual mode (build-time seed admission, build proofs) a caller advances the clock itself. Every
request is logged in served order with the step at which it was served, its method, path, query
or body, HTTP status, error, and the response body served; every accepted control change is logged
with the step at which it took effect, which is all the verifier needs to replay the run.

A logged telemetry or event-log response names a range of stream rows (packets in the order the
SCADA master closed them, events in log order) instead of repeating them; each row served at least
once is kept once in the session's tables, so the log holds exactly what was served and no more.
"""

from __future__ import annotations

import threading
import time

from .model import ControlError, forecast
from .params import N_STEPS, STEPS_PER_HOUR
from .scada import ALL_TAGS, RAW_QUOTA, RAW_SPAN, Scada

WALL_S_PER_HOUR = 150.0
WALL_S_PER_STEP = WALL_S_PER_HOUR / STEPS_PER_HOUR

# The documented operations; GET /api/v1/openapi.json is answered by the server itself.
ROUTES = {
    ("GET", "/api/v1/status"): "status",
    ("GET", "/api/v1/forecast"): "forecast",
    ("GET", "/api/v1/telemetry"): "telemetry",
    ("GET", "/api/v1/events"): "events",
    ("GET", "/api/v1/raw"): "raw",
    ("POST", "/api/v1/control"): "control",
}
_ROUTE_OF = {op: route for route, op in ROUTES.items()}
TABLES = ("telemetry_packets", "event_records")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Session:
    def __init__(self, seed: int, paced: bool = True, wall=time.monotonic, sink=None):
        self.seed = seed
        self.scada = Scada(seed)
        self.paced = paced
        self.wall = wall
        self.t0: float | None = None
        self.virtual_step = 0
        self.lock = threading.Lock()
        # Request log. With a sink (the server) each record and each newly served table row is
        # handed to the sink at once; without one they stay in memory.
        self.sink = sink
        self.served = 0
        self.requests: list[dict] = []
        self.tables: dict[str, dict[int, dict]] = {name: {} for name in TABLES}

    # ------------------------------------------------------------------ clock
    def now_step(self) -> int:
        if self.t0 is None:
            return 0
        if self.paced:
            return min(N_STEPS, int((self.wall() - self.t0) / WALL_S_PER_STEP))
        return min(N_STEPS, self.virtual_step)

    def set_virtual(self, step: int) -> None:
        self.virtual_step = max(self.virtual_step, min(N_STEPS, step))

    def _sync(self) -> int:
        if self.t0 is None:
            self.t0 = self.wall()
        step = self.now_step()
        self.scada.advance_to(step)
        return step

    def call(self, op: str, params: dict, request: dict | None = None) -> dict:
        """Serve one API operation; raises ApiError for a client error.

        ``request`` is the HTTP view of the call (method, path, target, query, body) when it
        came over HTTP; an in-process call is logged under its documented route.
        """
        with self.lock:
            starts = self.t0 is None
            step = self._sync()
            try:
                result = self._dispatch(op, params, step)
            except ApiError as exc:
                self._log(step, op, params, request, exc.status, exc.message,
                          {"error": exc.message})
                raise
            except Exception as exc:  # no response is served; the record says so
                self._log(step, op, params, request, None,
                          f"no response ({type(exc).__name__})", None)
                raise
            else:
                self._log(step, op, params, request, 200, None, result)
                return result
            finally:
                if self.sink is not None and (starts or op == "control"):
                    self.sink.action_log(self.action_log())

    def log_unrouted(self, request: dict, status: int | None, error: str | None,
                     response) -> None:
        """Log a request no operation serves (openapi.json, an unknown route or method, a
        malformed body, a refused request line). It does not start plant time."""
        with self.lock:
            self._log(self.now_step(), None, None, request, status, error, response)

    # ------------------------------------------------------------------ request log
    def _log(self, step: int, op, params, request, status, error, response) -> None:
        if request is None:
            method, path = _ROUTE_OF[op]
            request = {
                "method": method,
                "path": path,
                "target": None,
                "query": params if method == "GET" else {},
                "body": params if method == "POST" else None,
            }
        self.served += 1
        record = {
            "n": self.served,
            "step": step,
            "plant_hour": round(step / STEPS_PER_HOUR, 4),
            "method": request["method"],
            "path": request["path"],
            "target": request["target"],
            "query": request["query"],
            "body": request["body"],
            "status": status,
            "error": error,
            "response": self._logged_body(op, response),
        }
        if self.sink is None:
            self.requests.append(record)
        else:
            self.sink.request(record)

    def _logged_body(self, op, response):
        """The response as logged: telemetry packets and events become ranges of table rows."""
        if op == "telemetry" and isinstance(response, dict):
            ref = self._table_range(
                "telemetry_packets", self.scada.packets, response.get("packets"), True
            )
            if ref is not None:
                return {**response, "packets": ref}
        if op == "events" and isinstance(response, dict):
            rows = self.scada.events(float("-inf"))
            ref = self._table_range("event_records", rows, response.get("events"), False)
            if ref is not None:
                return {**response, "events": ref}
        return response

    def _table_range(self, name: str, stream: list, served, same: bool) -> dict | None:
        """``served`` as the stream rows [start, stop), keeping each newly served row once.

        ``same`` compares rows by identity (packets are shared objects); otherwise by value.
        Returns None when ``served`` is not one contiguous run of the stream.
        """
        if not isinstance(served, list):
            return None
        n = len(served)
        if n == 0:
            return {"table": name, "start": 0, "stop": 0}
        if same:
            start = next((i for i, row in enumerate(stream) if row is served[0]), None)
            match = start is not None and all(
                start + j < len(stream) and stream[start + j] is row
                for j, row in enumerate(served)
            )
        else:
            start = len(stream) - n
            match = start >= 0 and stream[start:] == served
        if not match:
            return None
        table = self.tables[name]
        new = [(start + j, row) for j, row in enumerate(served) if start + j not in table]
        for i, row in new:
            table[i] = row
        if new and self.sink is not None:
            self.sink.rows(name, new)
        return {"table": name, "start": start, "stop": start + n}
    def _dispatch(self, op: str, params: dict, step: int) -> dict:
        hour = step / STEPS_PER_HOUR
        sc = self.scada
        plant = sc.plant
        if op == "status":
            ramp_left = max(0, 120 - (plant.step_index - plant.ramp_start))
            return {
                "plant_hour": round(hour, 4),
                "contract_window_open": step >= 66 * STEPS_PER_HOUR,
                "ramp_active": ramp_left > 0,
                "ramp_remaining_s": ramp_left * 10,
                "changes_accepted": plant.accepted,
                "raw_quota_remaining": RAW_QUOTA - sc.raw_used,
                "setpoints": {
                    "supply_temp": plant.target["supply_temp"],
                    "pump_speed": plant.target["pump_speed"],
                    "boilers": list(plant.target["boilers"]),
                    "tank_rate": plant.target["tank_rate"],
                },
            }
        if op == "forecast":
            fc = forecast(sc.p)
            return {
                "issued_hour": 0,
                "hourly_ambient_c": [
                    {"hour": h, "ambient_c": t} for h, t in enumerate(fc[:72])
                ],
            }
        if op == "telemetry":
            from_h = _num(params, "from_hour", 0.0)
            to_h = params.get("to_hour")
            return {
                "plant_hour": round(hour, 4),
                "packets": sc.telemetry(
                    from_h, None if to_h is None else _num(params, "to_hour", 0.0)
                ),
            }
        if op == "events":
            return {
                "plant_hour": round(hour, 4),
                "events": sc.events(_num(params, "from_hour", 0.0)),
            }
        if op == "raw":
            tags = params.get("tags")
            if isinstance(tags, str):
                tags = [t for t in tags.split(",") if t]
            if (
                not isinstance(tags, list)
                or not tags
                or len(tags) > 8
                or any(t not in ALL_TAGS for t in tags)
            ):
                raise ApiError(400, "tags must name 1 to 8 known tags")
            start_h = _num(params, "start_hour", None)
            start = int(round(start_h * STEPS_PER_HOUR))
            if start < 0 or start + RAW_SPAN > step:
                raise ApiError(400, "the 30-minute span must lie entirely in the past")
            if sc.raw_used >= RAW_QUOTA:
                raise ApiError(429, "raw-sample quota exhausted")
            sc.raw_used += 1
            return {
                "start_hour": round(start / STEPS_PER_HOUR, 4),
                "samples": sc.raw(tags, start / STEPS_PER_HOUR),
                "raw_quota_remaining": RAW_QUOTA - sc.raw_used,
            }
        if op == "control":
            if step >= N_STEPS:
                raise ApiError(409, "the run has ended")
            try:
                result = plant.request(params)
            except ControlError as exc:
                raise ApiError(400, str(exc)) from None
            result["plant_hour"] = round(hour, 4)
            return result
        raise ApiError(404, "unknown operation")

    # ------------------------------------------------------------------ grading
    def finish(self) -> None:
        """Hold the last settings to hour 72 (the verifier replays the same)."""
        with self.lock:
            if self.t0 is None:
                return
            self.scada.advance_to(N_STEPS)

    def action_log(self) -> dict:
        plant = self.scada.plant
        return {
            "schema": "dh-plant-coldsnap-ops.action-log/v1",
            "started": self.t0 is not None,
            "controls": plant.control_log,
        }


def _num(params: dict, key: str, default):
    value = params.get(key, default)
    if value is None:
        raise ApiError(400, f"{key} is required")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be a number") from None
