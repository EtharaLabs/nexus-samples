"""Collect-step computations: O1-O4 from the replayed run, and the seed's expected incident set.

The O5 matcher lives with the verifier (tests/grade.py), not here.
"""

from __future__ import annotations

from plantops.session import replay

from . import terms as T
from .params import SPH, draw

ITEMS = ("O1", "O2", "O3", "O4")
OUT_OF_BAND_LIMIT_S = 600


def metrics_of(world) -> dict:
    m = world.plant.m
    served = m["served"]
    cost = m["cost_fuel"] + m["cost_import"] + m["cost_bat"]
    unit = cost / served if served > 1e-9 else float("inf")
    segs = [dict(sg) for sg in m["seg"].values()]
    gate = world.gate
    return {
        "segments": segs,
        "seg_margin_mwh": [round(sg["mwh"] - sg["contract"], 4) for sg in segs],
        "out_of_band_s": m["out_s"],
        "served_mwh": round(served, 4),
        "cost_eur": round(cost, 3),
        "cost_fuel": round(m["cost_fuel"], 3),
        "cost_import": round(m["cost_import"], 3),
        "cost_bat": round(m["cost_bat"], 3),
        "unit_cost": round(unit, 4),
        "cost_cap": T.COST_CAP,
        "min_gen_mw": round(m["min_gen"], 4),
        "hunt_s": m["hunt_s"],
        "unserved_mwh": round(m["unserved_mwh"], 5),
        "bat_min_soc": round(m["bat_min_soc"], 4),
        "accepted": gate.accepted,
        "rejected": gate.rejected,
        "O1": int(all(sg["mwh"] >= sg["contract"] for sg in segs)),
        "O2": int(m["out_s"] <= OUT_OF_BAND_LIMIT_S),
        "O3": int(unit <= T.COST_CAP),
        "O4": gate.o4(),
    }


def expected_incidents(seed: int) -> list[dict]:
    p = draw(seed)
    pk = (int(round(p["h_replay"] * SPH)) // 90) * 90  # replay starts on a 15-minute packet boundary
    return [
        {"kind": "sensor", "subject": p["bias_tag"], "onset_hour": 0.0, "value": None},
        {"kind": "sensor", "subject": p["drift_tag"], "onset_hour": round(p["h_drift"], 3), "value": None},
        {"kind": "sensor", "subject": p["unit_tag"], "onset_hour": round(p["h_unit"], 3), "value": None},
        {"kind": "sensor", "subject": p["replay_rtu"], "onset_hour": round(pk / SPH, 3), "value": None},
        {"kind": "equipment", "subject": p["gens"][p["fault_gen"]], "onset_hour": round(p["h_gov"], 3),
         "value": None},
        {"kind": "contract", "subject": p["dr_group"], "onset_hour": None, "value": None},
        {"kind": "operating_limit", "subject": "PT-BAT", "onset_hour": None,
         "value": round(p["p_derate"], 4)},
        {"kind": "operating_limit", "subject": "PG-GEN", "onset_hour": None, "value": round(p["pmin"], 4)},
    ]


class _GradingMember:
    """The member as the collect step replays it: the same world without the instrument layer, which
    never feeds back into the physics, so the scores are those of the observed run."""

    def __init__(self, member):
        self._member = member

    def make_world(self, seed: int):
        return self._member.make_world(seed, observe=False)


def collect(member, seed: int, log: dict) -> dict:
    world = replay(_GradingMember(member), seed, log)
    return {
        "scores": {k: metrics_of(world)[k] for k in ITEMS},
        "metrics": metrics_of(world),
        "expected_incidents": expected_incidents(seed),
    }
