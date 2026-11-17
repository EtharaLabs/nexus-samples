"""One trial's session: the plant clock, the API operations, and the grader-only logs.

Plant time starts at the first API call. In paced mode one plant hour takes 300 wall-clock seconds;
in virtual mode (build-time seed admission, build proofs) a caller advances the clock itself. Every
request is logged with the step at which it was served; every control request is logged with the
step at which it was served and whether it was accepted, which is all the collect step needs to
replay the run.

The member module (see ``plantops.member``) supplies ``make_world(seed)``, ``EXTRA_OPS``, and
``ACTION_LOG_SCHEMA``. A world exposes ``clock``, ``rtu`` (RtuLayer), ``gate`` (ControlGate),
``events`` (list), ``advance_to(step)``, ``request(step, change)``, and ``status(step)`` (the
member's extra status fields).
"""

from __future__ import annotations

import threading
import time

from .controls import ControlError
from .rtu import format_events

RAW_TAG_LIMIT = 8


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Session:
    def __init__(self, member, seed: int, paced: bool = True, wall=time.monotonic):
        self.member = member
        self.seed = seed
        self.world = member.make_world(seed)
        self.clock = self.world.clock
        self.paced = paced
        self.wall = wall
        self.t0: float | None = None
        self.virtual_step = 0
        self.lock = threading.Lock()
        self.requests: list[dict] = []

    # ------------------------------------------------------------------ clock
    def now_step(self) -> int:
        if self.t0 is None:
            return 0
        n = self.clock.n_steps
        if self.paced:
            return min(n, int((self.wall() - self.t0) / self.clock.wall_s_per_step))
        return min(n, self.virtual_step)

    def set_virtual(self, step: int) -> None:
        self.virtual_step = max(self.virtual_step, min(self.clock.n_steps, step))

    def _sync(self) -> int:
        if self.t0 is None:
            self.t0 = self.wall()
        step = self.now_step()
        self.world.advance_to(step)
        return step

    def call(self, op: str, params: dict) -> dict:
        """Serve one API operation; raises ApiError for a client error."""
        with self.lock:
            step = self._sync()
            entry = {"step": step, "op": op, "params": params}
            try:
                result = self._dispatch(op, params, step)
                entry["status"] = 200
                return result
            except ApiError as exc:
                entry["status"] = exc.status
                entry["error"] = exc.message
                raise
            finally:
                self.requests.append(entry)

    def _dispatch(self, op: str, params: dict, step: int) -> dict:
        c = self.clock
        w = self.world
        hour = c.hour(step)
        if op == "status":
            out = {
                "plant_hour": round(hour, 4),
                "contract_window_open": step >= c.window_start,
                "ramp_active": w.gate.in_ramp(step),
                "ramp_remaining_s": w.gate.ramp_remaining_s(step),
                "changes_accepted": w.gate.accepted,
                "raw_quota_remaining": w.rtu.raw_quota_remaining(),
            }
            out.update(w.status(step))
            return out
        if op == "telemetry":
            from_h = number(params, "from_hour", 0.0)
            to_h = params.get("to_hour")
            return {
                "plant_hour": round(hour, 4),
                "packets": w.rtu.telemetry(
                    from_h, None if to_h is None else number(params, "to_hour", 0.0)
                ),
            }
        if op == "events":
            return {
                "plant_hour": round(hour, 4),
                "events": format_events(w.events, c, number(params, "from_hour", 0.0)),
            }
        if op == "raw":
            tags = params.get("tags")
            if isinstance(tags, str):
                tags = [t for t in tags.split(",") if t]
            if (
                not isinstance(tags, list)
                or not tags
                or len(tags) > RAW_TAG_LIMIT
                or any(t not in w.rtu.tag_rtu for t in tags)
            ):
                raise ApiError(400, f"tags must name 1 to {RAW_TAG_LIMIT} known tags")
            start = c.step_at(number(params, "start_hour", None))
            if start < 0 or start + c.raw_span > step:
                raise ApiError(400, "the 30-minute span must lie entirely in the past")
            if w.rtu.raw_quota_remaining() <= 0:
                raise ApiError(429, "raw-sample quota exhausted")
            w.rtu.raw_used += 1
            return {
                "start_hour": round(c.hour(start), 4),
                "samples": w.rtu.raw(tags, start),
                "raw_quota_remaining": w.rtu.raw_quota_remaining(),
            }
        if op == "control":
            if step >= c.n_steps:
                raise ApiError(409, "the run has ended")
            try:
                result = w.request(step, params)
            except ControlError as exc:
                raise ApiError(400, str(exc)) from None
            result["plant_hour"] = round(hour, 4)
            return result
        extra = self.member.EXTRA_OPS.get(op)
        if extra is not None:
            try:
                return extra(w, params, step)
            except ControlError as exc:
                raise ApiError(400, str(exc)) from None
        raise ApiError(404, "unknown operation")

    # ------------------------------------------------------------------ grading
    def finish(self) -> None:
        """Hold the last settings to hour 72 (the collect step replays the same)."""
        with self.lock:
            if self.t0 is None:
                return
            self.world.advance_to(self.clock.n_steps)

    def action_log(self) -> dict:
        return {
            "schema": self.member.ACTION_LOG_SCHEMA,
            "started": self.t0 is not None,
            "controls": self.world.gate.control_log,
        }


def number(params: dict, key: str, default):
    value = params.get(key, default)
    if value is None:
        raise ApiError(400, f"{key} is required")
    if isinstance(value, bool):
        raise ApiError(400, f"{key} must be a number")
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be a number") from None
    if out != out or out in (float("inf"), float("-inf")):
        raise ApiError(400, f"{key} must be a number")
    return out


def replay(member, seed: int, log: dict):
    """Re-run the world from ``seed`` with every logged control request at its logged step.

    Used by the collect step; raises ValueError when the log does not replay."""
    world = member.make_world(seed)
    n = world.clock.n_steps
    last = 0
    for entry in log.get("controls", []):
        step = int(entry["step"])
        if step < last or step >= n:
            raise ValueError("action log is not ordered or lies outside the run")
        last = step
        world.advance_to(step)
        result = world.request(step, entry["change"])
        if bool(result["accepted"]) != bool(entry["accepted"]):
            raise ValueError(f"action log does not replay at step {step}")
    world.advance_to(n)
    return world
