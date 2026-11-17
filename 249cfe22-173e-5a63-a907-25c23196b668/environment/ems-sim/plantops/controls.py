"""The change rules every member's CONTRACT.md states (rules 4 to 6 of the family).

At most 40 accepted changes; one request setting several controls counts once. Each accepted change
starts a 20-minute ramp. A request received during a ramp, or at or after hour 66, is rejected, not
applied, and counts as a breach. A malformed or out-of-range request raises ControlError (HTTP 400):
neither a change nor a breach.

Numeric controls named in ``ramped`` move linearly from their value at the request to the new
target over the ramp; every other control takes its new value at once.
"""

from __future__ import annotations

from typing import Callable

from .clock import MAX_CHANGES, Clock


class ControlError(Exception):
    pass


class ControlSpec:
    """``numeric``: name -> (lo, hi); ``other``: name -> validator(value) returning the clean value
    or raising ControlError; ``ramped``: the numeric names that ramp."""

    def __init__(
        self,
        numeric: dict[str, tuple[float, float]],
        other: dict[str, Callable[[object], object]] | None = None,
        ramped: tuple[str, ...] = (),
        decimals: int = 3,
    ):
        self.numeric = dict(numeric)
        self.other = dict(other or {})
        self.ramped = tuple(ramped)
        self.decimals = decimals
        unknown = set(self.ramped) - set(self.numeric)
        if unknown:
            raise ValueError(f"ramped controls must be numeric: {sorted(unknown)}")

    def names(self) -> list[str]:
        return list(self.numeric) + list(self.other)

    def validate(self, change) -> dict:
        if not isinstance(change, dict) or not change:
            raise ControlError(
                "a control request sets at least one of " + ", ".join(self.names())
            )
        clean: dict = {}
        for key, value in change.items():
            if key in self.numeric:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ControlError(f"{key} must be a number")
                lo, hi = self.numeric[key]
                if not (lo <= float(value) <= hi):
                    raise ControlError(f"{key} must be between {lo:g} and {hi:g}")
                clean[key] = round(float(value), self.decimals)
            elif key in self.other:
                clean[key] = self.other[key](value)
            else:
                raise ControlError(f"unknown control {key!r}")
        return clean


class ControlGate:
    def __init__(self, clock: Clock, spec: ControlSpec, initial: dict, events: list):
        self.clock = clock
        self.spec = spec
        self.target = {k: _copy(v) for k, v in initial.items()}
        self.cur = {k: self.target[k] for k in spec.ramped}
        self.start_vals = dict(self.cur)
        self.ramp_start = -clock.ramp_steps
        self.accepted = 0
        self.rejected = 0
        self.control_log: list[dict] = []
        self.rejections: list[dict] = []
        self.events = events

    def in_ramp(self, step: int) -> bool:
        return step - self.ramp_start < self.clock.ramp_steps

    def ramp_remaining_s(self, step: int) -> int:
        return (
            max(0, self.clock.ramp_steps - (step - self.ramp_start)) * self.clock.step_s
        )

    def request(self, step: int, change) -> dict:
        clean = self.spec.validate(change)
        if step >= self.clock.window_start or self.in_ramp(step):
            reason = "window" if step >= self.clock.window_start else "ramp"
            self.rejected += 1
            self.rejections.append({"step": step, "change": clean, "reason": reason})
            self.control_log.append({"step": step, "change": clean, "accepted": False})
            self.events.append(
                {
                    "step": step,
                    "source": "CTRL",
                    "event": "control_rejected",
                    "reason": reason,
                    "change": clean,
                }
            )
            return {"accepted": False, "reason": reason}
        self.start_vals = {k: self.cur[k] for k in self.spec.ramped}
        for key, value in clean.items():
            self.target[key] = _copy(value)
        self.ramp_start = step
        self.accepted += 1
        self.control_log.append({"step": step, "change": clean, "accepted": True})
        self.events.append(
            {"step": step, "source": "CTRL", "event": "control_change", "change": clean}
        )
        return {"accepted": True}

    def tick(self, step: int) -> None:
        """Advance the ramped values to ``step``."""
        frac = (step - self.ramp_start) / self.clock.ramp_steps
        for key in self.spec.ramped:
            if frac >= 1.0:
                self.cur[key] = self.target[key]
            else:
                a = self.start_vals[key]
                self.cur[key] = a + (self.target[key] - a) * frac

    def value(self, key: str):
        return self.cur[key] if key in self.cur else self.target[key]

    def o4(self) -> int:
        return 1 if self.accepted <= MAX_CHANGES and self.rejected == 0 else 0


def _copy(v):
    return list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)
