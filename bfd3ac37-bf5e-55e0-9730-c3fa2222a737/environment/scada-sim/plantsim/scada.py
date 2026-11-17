"""The SCADA layer: what the plant's meters and RTUs report.

Every value an API response carries comes from here. Sensor faults (a biased heat meter, a
drifting heat meter, a firmware unit change, a replaying RTU) and the far-branch RTU's
report-by-exception logging are applied at measurement time, so no response ever carries a
physical quantity the meters do not measure.
"""

from __future__ import annotations

import random

from .model import Plant
from .params import N_STEPS, STEPS_PER_HOUR, SUBSTATIONS

INTERVAL = 90  # steps per 15-minute telemetry interval
RAW_SPAN = 180  # steps per 30-minute raw-sample request
RAW_QUOTA = 40
M3H_PER_KGS = 3.6 / 0.98  # the firmware 4.2.0 flow unit: m3/h at 0.98 t/m3

PLANT_TAGS = (
    "TT-100",
    "TT-101",
    "FT-100",
    "FT-110",
    "FT-130",
    "PT-100",
    "LT-200",
    "JT-200",
    "SC-100",
    "TT-AMB",
)
BOILER_TAGS = ("JT-B1", "JT-B2", "JT-B3", "FQ-B1", "FQ-B2", "FQ-B3")
FAR_TAGS = ("FT-120", "ZT-120")
RTUS: dict[str, tuple[str, ...]] = {
    "RTU-PLANT": PLANT_TAGS,
    "RTU-BLR": BOILER_TAGS,
    "RTU-FAR": FAR_TAGS,
}
for _k, _s in enumerate(SUBSTATIONS):
    RTUS["RTU-" + _s] = ("TT-" + _s, "FT-" + _s, "JQ-" + _s)
TAG_RTU = {tag: rtu for rtu, tags in RTUS.items() for tag in tags}
ALL_TAGS = tuple(TAG_RTU)
UNITS = {
    "TT": "C",
    "FT": "kg/s",
    "PT": "bar(g)",
    "LT": "%",
    "JT": "MW",
    "SC": "fraction",
    "FQ": "MW",
    "ZT": "%",
    "JQ": "MW",
}
CENSORED = set(FAR_TAGS)
REPLAY_SPAN = 2 * STEPS_PER_HOUR
REPLAY_PACKETS = REPLAY_SPAN // INTERVAL


class Scada:
    def __init__(self, seed: int):
        self.plant = Plant(seed, observer=self)
        p = self.plant.p
        self.p = p
        self.rng = random.Random(p["noise_seed"])
        self.values: dict[str, list[float]] = {
            tag: [] for tag in ALL_TAGS if tag not in CENSORED
        }
        self.logged: list[tuple[int, float, float]] = []  # (step, FT-120, ZT-120)
        self._last_u = None
        boot = random.Random(p["noise_seed"] ^ 0x5EED)
        self.seq0 = {rtu: boot.randrange(1000, 60000) for rtu in RTUS}
        self.uptime0 = {rtu: boot.randrange(3600, 9 * 86400) for rtu in RTUS}
        self.packets: list[dict] = []
        self._own: dict[str, list[dict]] = {rtu: [] for rtu in RTUS}
        self._held: dict[str, float | None] = {"FT-120": None, "ZT-120": None}
        sub = SUBSTATIONS
        self.replay_rtu = "RTU-" + sub[p["replay_sub"]]
        rs = int(round(p["h_replay"] * STEPS_PER_HOUR))
        self.replay_step = (
            rs // INTERVAL
        ) * INTERVAL  # the replay starts on an interval boundary
        self.bias_tag = "JQ-" + sub[p["bias_sub"]]
        self.drift_tag = "JQ-" + sub[p["drift_sub"]]
        self.unit_tag = "FT-" + sub[p["unit_sub"]]
        self.unit_step = int(p["h_unit"] * STEPS_PER_HOUR) + 1
        self.raw_used = 0

    # --------------------------------------------------------------- measurement
    def _n(self, sigma: float) -> float:
        r = self.rng.random
        return sigma * (r() + r() + r() + r() - 2.0) * 1.7320508075688772

    def observe(self, i: int, s: dict) -> None:
        p = self.p
        v = self.values
        n = self._n
        hour = i / STEPS_PER_HOUR
        v["TT-100"].append(s["ts"] + n(0.05))
        v["TT-101"].append(s["tpr"] + n(0.05))
        v["FT-100"].append(s["qp"] * (1.0 + n(0.003)))
        v["FT-110"].append(s["qn"] * (1.0 + n(0.003)))
        v["FT-130"].append(max(0.0, s["byp"] + n(0.3)))
        v["PT-100"].append(s["pin"] + n(0.002))
        v["LT-200"].append(100.0 * s["lev"] + n(0.05))
        v["JT-200"].append(s["tank"] + n(0.02))
        v["SC-100"].append(round(s["spd"], 3))
        v["TT-AMB"].append(s["amb"] + n(0.1))
        for j in range(3):
            v[f"JT-B{j + 1}"].append(s["out_b"][j] * (1.0 + n(0.005)))
            v[f"FQ-B{j + 1}"].append(s["fuel"][j] * (1.0 + n(0.005)))
        for k, name in enumerate(SUBSTATIONS):
            v["TT-" + name].append(s["tr"][k] + n(0.05))
            flow = s["q"][k] * (1.0 + n(0.003))
            if "FT-" + name == self.unit_tag and i >= self.unit_step:
                flow *= M3H_PER_KGS
            v["FT-" + name].append(flow)
            heat = s["heat"][k] * (1.0 + n(0.005))
            tag = "JQ-" + name
            if tag == self.bias_tag:
                heat *= p["bias_factor"]
            if tag == self.drift_tag and hour >= p["h_drift"]:
                heat *= 1.0 + p["drift_rate"] * (hour - p["h_drift"])
            v[tag].append(heat)
        u = s["u_far"]
        if self._last_u is None or abs(u - self._last_u) > 0.02:
            self._last_u = u
            self.logged.append((i, s["qf"] * (1.0 + n(0.003)), 100.0 * u))
        if (i + 1) % INTERVAL == 0:
            self._close_interval(i + 1)

    def _value(self, tag: str, i: int) -> float:
        """The value the SCADA master received for ``tag`` at step ``i`` (replay applied)."""
        if TAG_RTU[tag] == self.replay_rtu and i >= self.replay_step:
            i = self.replay_step - REPLAY_SPAN + (i - self.replay_step) % REPLAY_SPAN
        return self.values[tag][i]

    def _close_interval(self, end: int) -> None:
        start = end - INTERVAL
        index = end // INTERVAL - 1
        for rtu, tags in RTUS.items():
            if rtu == "RTU-FAR":
                inside = [x for x in self.logged if start <= x[0] < end]
                if inside:
                    self._held["FT-120"] = sum(x[1] for x in inside) / len(inside)
                    self._held["ZT-120"] = sum(x[2] for x in inside) / len(inside)
                values: dict[str, float | None] = {}
                for t in tags:
                    held = self._held[t]
                    values[t] = round(held, 3) if held is not None else None
                own = {
                    "seq": self.seq0[rtu] + index,
                    "uptime_s": self.uptime0[rtu] + end * 10,
                    "values": values,
                }
            elif rtu == self.replay_rtu and start >= self.replay_step:
                k = (start - self.replay_step) // INTERVAL
                base = self.replay_step // INTERVAL - REPLAY_PACKETS
                src = self._own[rtu][base + k % REPLAY_PACKETS]
                own = {
                    "seq": src["seq"],
                    "uptime_s": src["uptime_s"],
                    "values": dict(src["values"]),
                }
            else:
                values = {
                    t: round(sum(self.values[t][start:end]) / INTERVAL, 3) for t in tags
                }
                own = {
                    "seq": self.seq0[rtu] + index,
                    "uptime_s": self.uptime0[rtu] + end * 10,
                    "values": values,
                }
            self._own[rtu].append(own)
            self.packets.append(
                {
                    "rtu": rtu,
                    "interval_start_h": round(start / STEPS_PER_HOUR, 4),
                    "interval_end_h": round(end / STEPS_PER_HOUR, 4),
                    **own,
                }
            )

    # --------------------------------------------------------------- queries
    def advance_to(self, step: int) -> None:
        self.plant.advance_to(min(step, N_STEPS))

    def telemetry(self, from_h: float = 0.0, to_h: float | None = None) -> list[dict]:
        return [
            pk
            for pk in self.packets
            if pk["interval_start_h"] >= from_h
            and (to_h is None or pk["interval_end_h"] <= to_h)
        ]

    def raw(self, tags: list[str], start_h: float) -> dict:
        start = int(round(start_h * STEPS_PER_HOUR))
        end = start + RAW_SPAN
        out: dict = {}
        for tag in tags:
            if tag in CENSORED:
                col = 1 if tag == "FT-120" else 2
                out[tag] = [
                    [round(x[0] * 10 / 3600.0, 5), round(x[col], 3)]
                    for x in self.logged
                    if start <= x[0] < end
                ]
            else:
                out[tag] = [
                    [round(i * 10 / 3600.0, 5), round(self._value(tag, i), 3)]
                    for i in range(start, end)
                ]
        return out

    def events(self, from_h: float = 0.0) -> list[dict]:
        out = []
        for e in self.plant.events:
            h = e["step"] / STEPS_PER_HOUR
            if h >= from_h:
                item = {k: v for k, v in e.items() if k != "step"}
                item["hour"] = round(h, 4)
                out.append(item)
        return out
