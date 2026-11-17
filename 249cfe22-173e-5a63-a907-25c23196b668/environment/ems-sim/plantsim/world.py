"""The world a session serves: the plant, its instruments (the RTU layer), and the control gate."""

from __future__ import annotations

from plantops.clock import Clock
from plantops.controls import ControlError, ControlGate, ControlSpec
from plantops.rtu import RtuLayer

from . import terms as T
from .model import Plant
from .params import DEADBAND_HZ, GROUPS, N_STEPS, STEP_S, SUB, draw

CLOCK = Clock(STEP_S)
INITIAL = {"g1_mw": 1.8, "g2_mw": 1.8, "bat_mw": 0.0, "pv_curtail": 0.0, "shed": []}


def _shed(value):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ControlError("shed must be a list of load group ids")
    if len(set(value)) != len(value) or any(x not in GROUPS for x in value):
        raise ControlError("shed must name distinct load groups from " + ", ".join(GROUPS))
    return sorted(value, key=GROUPS.index)


SPEC = ControlSpec(
    numeric={"g1_mw": (0.0, 3.0), "g2_mw": (0.0, 3.0), "bat_mw": (-2.6, 2.6), "pv_curtail": (0.0, 1.0)},
    other={"shed": _shed},
    ramped=("g1_mw", "g2_mw", "bat_mw", "pv_curtail"),
)

RTUS = {
    "RTU-BUS": ("F-SYS", "PT-TIE", "PT-PV", "PT-BAT", "SOC-BAT"),
    "RTU-GEN": ("PG-G1", "PG-G2", "FQ-G1", "FQ-G2"),
    "RTU-FREQ": ("F-GEN",),
}
for _g in GROUPS:
    RTUS["RTU-" + _g] = ("PM-" + _g,)
NOISE = {
    "F-SYS": ("abs", 0.004), "PT-TIE": ("abs", 0.01), "PT-PV": ("abs", 0.01),
    "PT-BAT": ("abs", 0.01), "SOC-BAT": ("abs", 0.02), "PG-G1": ("abs", 0.01),
    "PG-G2": ("abs", 0.01), "FQ-G1": ("abs", 0.012), "FQ-G2": ("abs", 0.012),
    "F-GEN": ("abs", 0.004),
}
for _g in GROUPS:
    NOISE["PM-" + _g] = ("abs", 0.004)


def faults(p: dict) -> dict:
    return {
        "bias_tag": p["bias_tag"], "bias_kind": "mul", "bias_value": p["bias_factor"],
        "drift_tag": p["drift_tag"], "drift_kind": "mul", "drift_start_h": p["h_drift"],
        "drift_rate": p["drift_rate"],
        "unit_tag": p["unit_tag"], "unit_step": int(p["h_unit"] * CLOCK.steps_per_hour) + 1,
        "unit_scale": 1000.0, "unit_offset": 0.0,
        "replay_rtu": p["replay_rtu"], "replay_start_h": p["h_replay"],
    }


class World:
    def __init__(self, seed: int, observe: bool = True):
        p = draw(seed)
        self.p = p
        self.clock = CLOCK
        self.events: list = []
        self.gate = ControlGate(CLOCK, SPEC, INITIAL, self.events)
        self.rtu = None
        obs = None
        if observe:
            self.rtu = RtuLayer(
                CLOCK, RTUS, NOISE, p["noise_seed"], faults(p),
                censored={"rtu": "RTU-FREQ", "trigger": "F-GEN", "deadband": DEADBAND_HZ},
                raw_every=1, decimals=4, sub=SUB,
            )
            obs = self._observe
        self.plant = Plant(seed, self.gate, self.events, obs)

    def _observe(self, i: int, s: dict) -> None:
        t = {
            "F-SYS": s["f_sys"], "PT-TIE": s["tie"], "PT-PV": s["pv"], "PT-BAT": s["bat"],
            "SOC-BAT": 100.0 * s["soc"], "PG-G1": s["out"][0], "PG-G2": s["out"][1],
            "FQ-G1": s["fuel"][0], "FQ-G2": s["fuel"][1], "F-GEN": s["f_bus"],
        }
        for g in GROUPS:
            t["PM-" + g] = s["load"][g]
        self.rtu.observe(i, t)

    # ----------------------------------------------------------- the session interface
    def advance_to(self, step: int) -> None:
        step = min(step, N_STEPS)
        while self.plant.i < step:
            self.plant.step()

    def request(self, step: int, change) -> dict:
        return self.gate.request(step, change)

    def status(self, step: int) -> dict:
        t = self.gate.target
        return {"setpoints": {"g1_mw": t["g1_mw"], "g2_mw": t["g2_mw"], "bat_mw": t["bat_mw"],
                              "pv_curtail": t["pv_curtail"], "shed": list(t["shed"])}}
