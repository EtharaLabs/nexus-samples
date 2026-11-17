"""Collect-step computations: replay of an action log, the expected incident set, and O1-O4.

The sidecar's collect step (finalize.py) runs these after the agent's container has stopped. The
incident-report matcher (O5) lives with the verifier in tests/grade.py, not here.
"""

from __future__ import annotations

from .model import CONTRACTED_MWH, COST_CAP, Plant, validate
from .params import N_STEPS, STEPS_PER_HOUR, SUBSTATIONS, draw
from .scada import INTERVAL

ITEMS = ("O1", "O2", "O3", "O4")


def replay(seed: int, log: dict) -> Plant:
    """Re-run the plant from ``seed`` with every logged control request at its logged step."""
    plant = Plant(seed)
    for entry in log.get("controls", []):
        step = int(entry["step"])
        if step < plant.step_index or step >= N_STEPS:
            raise ValueError("action log is not ordered or lies outside the run")
        plant.advance_to(step)
        result = plant.request(validate(entry["change"]))
        if bool(result["accepted"]) != bool(entry["accepted"]):
            raise ValueError(f"action log does not replay at step {step}")
    plant.advance_to(N_STEPS)
    return plant


def expected_incidents(seed: int) -> list[dict]:
    p = draw(seed)
    plant = Plant(seed)
    q_osc = plant.q_osc
    replay_step = (int(round(p["h_replay"] * STEPS_PER_HOUR)) // INTERVAL) * INTERVAL
    s = SUBSTATIONS
    return [
        {
            "kind": "sensor",
            "subject": "JQ-" + s[p["bias_sub"]],
            "onset_hour": 0.0,
            "value": None,
        },
        {
            "kind": "sensor",
            "subject": "JQ-" + s[p["drift_sub"]],
            "onset_hour": round(p["h_drift"], 3),
            "value": None,
        },
        {
            "kind": "sensor",
            "subject": "FT-" + s[p["unit_sub"]],
            "onset_hour": round(p["h_unit"], 3),
            "value": None,
        },
        {
            "kind": "sensor",
            "subject": "RTU-" + s[p["replay_sub"]],
            "onset_hour": round(replay_step / STEPS_PER_HOUR, 3),
            "value": None,
        },
        {
            "kind": "equipment",
            "subject": "B2",
            "onset_hour": round(p["h_b2fault"], 3),
            "value": None,
        },
        {
            "kind": "contract",
            "subject": s[p["decoy"]],
            "onset_hour": None,
            "value": None,
        },
        {
            "kind": "operating_limit",
            "subject": "FT-100",
            "onset_hour": None,
            "value": round(q_osc, 2),
        },
        {
            "kind": "operating_limit",
            "subject": "FT-120",
            "onset_hour": None,
            "value": round(p["q_sat"], 2),
        },
    ]


def collect(seed: int, log: dict) -> dict:
    """Replay the run and return its metrics, O1-O4, and the seed's expected incident set."""
    metrics = replay(seed, log).metrics()
    metrics["contracted_mwh"] = CONTRACTED_MWH
    metrics["cost_cap"] = COST_CAP
    return {
        "scores": {item: metrics[item] for item in ITEMS},
        "metrics": metrics,
        "expected_incidents": expected_incidents(seed),
    }
