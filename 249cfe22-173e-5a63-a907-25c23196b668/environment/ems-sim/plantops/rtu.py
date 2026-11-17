"""The measurement layer: what the plant's meters and RTUs report.

Every value an API response carries comes from here. The member hands ``observe`` the true value of
every tag at every simulation step; this layer adds instrument noise and applies the four sensor and
RTU faults of the family (a biased meter, a drifting meter, a firmware unit change, a replaying RTU)
and the censored RTU's report-by-exception logging. No response ever carries a quantity the
instruments do not measure.

Fault specification (``faults``), every key required:
  bias_tag, bias_kind ("mul" | "add"), bias_value
  drift_tag, drift_kind ("mul" | "add"), drift_start_h, drift_rate (per plant hour)
  unit_tag, unit_step, unit_scale, unit_offset   (after unit_step: reported = scale * v + offset)
  replay_rtu, replay_start_h                      (floored to the 15-minute packet grid)
Sub-sampling (``sub``, default 1): each simulation step carries ``sub`` raw samples, so a member with a
coarse physics step can still report raw samples at a finer resolution. A tag's true value is a float
(held across the step's samples, noise drawn per sample) or a sequence of ``sub`` floats. Raw samples
are returned every ``raw_every`` samples; telemetry averages every sample in the interval.
Censoring (``censored``, optional): {"rtu": id, "trigger": tag, "deadband": float}; that RTU's tags
are logged together only when the trigger tag moves more than the deadband from its last logged
value; its 15-minute packet carries the mean of the points logged in the interval, or the last
logged values when none was.
"""

from __future__ import annotations

import random
from array import array

from .clock import RAW_QUOTA, Clock

REPLAY_HOURS = 2


class RtuLayer:
    def __init__(
        self,
        clock: Clock,
        rtus: dict[str, tuple[str, ...]],
        noise: dict[str, tuple[str, float]],
        noise_seed: int,
        faults: dict,
        censored: dict | None = None,
        raw_every: int = 1,
        decimals: int = 3,
        sub: int = 1,
    ):
        self.clock = clock
        self.rtus = {r: tuple(t) for r, t in rtus.items()}
        self.tag_rtu = {tag: r for r, tags in self.rtus.items() for tag in tags}
        self.tags = tuple(self.tag_rtu)
        missing = [t for t in self.tags if t not in noise]
        if missing:
            raise ValueError(f"noise model missing for {missing}")
        self.noise = noise
        self.rng = random.Random(noise_seed)
        boot = random.Random(noise_seed ^ 0x5EED)
        self.seq0 = {r: boot.randrange(1000, 60000) for r in self.rtus}
        self.uptime0 = {r: boot.randrange(3600, 9 * 86400) for r in self.rtus}
        self.f = dict(faults)
        self.censored = dict(censored) if censored else None
        self.c_tags = self.rtus[self.censored["rtu"]] if self.censored else ()
        self.raw_every = raw_every
        self.sub = sub
        self.decimals = decimals
        self.values = {t: array("d") for t in self.tags if t not in self.c_tags}
        self._sums = {t: 0.0 for t in self.values}
        self.logged: list[tuple[int, dict[str, float]]] = []
        self._pending: dict[str, float] = {}
        self._last_trigger: float | None = None
        self._held: dict[str, float | None] = {t: None for t in self.c_tags}
        self.packets: list[dict] = []
        self._own: dict[str, list[dict]] = {r: [] for r in self.rtus}
        span = REPLAY_HOURS * clock.steps_per_hour
        start = clock.step_at(self.f["replay_start_h"])
        self.replay_step = (start // clock.interval) * clock.interval
        self.replay_span = span
        self.raw_used = 0
        self.step_index = 0

    # ------------------------------------------------------------------ measurement
    def _n(self, sigma: float) -> float:
        r = self.rng.random
        return sigma * (r() + r() + r() + r() - 2.0) * 1.7320508075688772

    def _faulted(self, tag: str, v: float, i: int) -> float:
        f = self.f
        hour = self.clock.hour(i)
        if tag == f["bias_tag"]:
            v = v * f["bias_value"] if f["bias_kind"] == "mul" else v + f["bias_value"]
        if tag == f["drift_tag"] and hour >= f["drift_start_h"]:
            d = f["drift_rate"] * (hour - f["drift_start_h"])
            v = v * (1.0 + d) if f["drift_kind"] == "mul" else v + d
        if tag == f["unit_tag"] and i >= f["unit_step"]:
            v = f["unit_scale"] * v + f["unit_offset"]
        return v

    def observe(self, i: int, true: dict[str, float]) -> None:
        """Record step ``i``. ``true`` maps every tag to its true value."""
        n = self._n
        sub = self.sub
        for tag in self.tags:
            kind, sigma = self.noise[tag]
            given = true[tag]
            seq = given if isinstance(given, (list, tuple)) else (given,) * sub
            if len(seq) != sub:
                raise ValueError(f"{tag}: expected {sub} sub-samples")
            for v in seq:
                if kind == "rel":
                    v = v * (1.0 + n(sigma))
                elif kind == "abs":
                    v = v + n(sigma)
                # kind "none": a commanded or digital value, reported exactly
                v = self._faulted(tag, v, i)
                if tag in self.values:
                    self.values[tag].append(v)
                    self._sums[tag] += v
                else:
                    self._pending[tag] = v
        if self.censored:
            trig = self._pending[self.censored["trigger"]]
            if (
                self._last_trigger is None
                or abs(trig - self._last_trigger) > self.censored["deadband"]
            ):
                self._last_trigger = trig
                self.logged.append((i, {t: self._pending[t] for t in self.c_tags}))
        self.step_index = i + 1
        if (i + 1) % self.clock.interval == 0:
            self._close_interval(i + 1)

    def _value(self, tag: str, i: int) -> float:
        """The value the master received for ``tag`` at raw sample ``i`` (replay applied)."""
        rs, span = self.replay_step * self.sub, self.replay_span * self.sub
        if self.tag_rtu[tag] == self.f["replay_rtu"] and i >= rs:
            i = rs - span + (i - rs) % span
        return self.values[tag][i]

    def _close_interval(self, end: int) -> None:
        c = self.clock
        start = end - c.interval
        index = end // c.interval - 1
        d = self.decimals
        for rtu, tags in self.rtus.items():
            if self.censored and rtu == self.censored["rtu"]:
                inside = [x for x in self.logged if start <= x[0] < end]
                if inside:
                    for t in tags:
                        self._held[t] = sum(x[1][t] for x in inside) / len(inside)
                own = {
                    "seq": self.seq0[rtu] + index,
                    "uptime_s": self.uptime0[rtu] + end * c.step_s,
                    "values": {
                        t: (
                            round(self._held[t], d)
                            if self._held[t] is not None
                            else None
                        )
                        for t in tags
                    },
                }
            elif rtu == self.f["replay_rtu"] and start >= self.replay_step:
                per = self.replay_span // c.interval
                k = (start - self.replay_step) // c.interval
                base = self.replay_step // c.interval - per
                src = self._own[rtu][base + k % per]
                own = {
                    "seq": src["seq"],
                    "uptime_s": src["uptime_s"],
                    "values": dict(src["values"]),
                }
            else:
                own = {
                    "seq": self.seq0[rtu] + index,
                    "uptime_s": self.uptime0[rtu] + end * c.step_s,
                    "values": {
                        t: round(self._sums[t] / (c.interval * self.sub), d) for t in tags
                    },
                }
            self._own[rtu].append(own)
            self.packets.append(
                {
                    "rtu": rtu,
                    "interval_start_h": round(c.hour(start), 4),
                    "interval_end_h": round(c.hour(end), 4),
                    **own,
                }
            )
        for t in self._sums:
            self._sums[t] = 0.0

    # ------------------------------------------------------------------ queries
    def telemetry(self, from_h: float = 0.0, to_h: float | None = None) -> list[dict]:
        return [
            pk
            for pk in self.packets
            if pk["interval_start_h"] >= from_h
            and (to_h is None or pk["interval_end_h"] <= to_h)
        ]

    def raw_quota_remaining(self) -> int:
        return RAW_QUOTA - self.raw_used

    def raw(self, tags: list[str], start: int) -> dict:
        """Samples of ``tags`` over the 30-minute span from step ``start`` at the raw resolution.
        The caller has validated the span and charged the quota."""
        c = self.clock
        end = start + c.raw_span
        d = self.decimals
        out: dict = {}
        for tag in tags:
            if tag in self.c_tags:
                out[tag] = [
                    [round(c.hour(x[0]), 5), round(x[1][tag], d)]
                    for x in self.logged
                    if start <= x[0] < end
                ]
            else:
                per_h = c.steps_per_hour * self.sub
                out[tag] = [
                    [round(k / per_h, 6), round(self._value(tag, k), d)]
                    for k in range(start * self.sub, end * self.sub, self.raw_every)
                ]
        return out


def format_events(events: list[dict], clock: Clock, from_h: float = 0.0) -> list[dict]:
    out = []
    for e in events:
        h = clock.hour(e["step"])
        if h >= from_h:
            item = {k: v for k, v in e.items() if k != "step"}
            item["hour"] = round(h, 4)
            out.append(item)
    return out
