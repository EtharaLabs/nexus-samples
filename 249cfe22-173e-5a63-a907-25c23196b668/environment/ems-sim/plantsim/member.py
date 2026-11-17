"""The member interface the shared sidecar (plantops) loads: clock, schemas, extra routes, world."""

from __future__ import annotations

from . import grading, model, terms
from .openapi import SPEC  # noqa: F401 - exported
from .params import GROUPS
from .world import CLOCK, World  # noqa: F401 - CLOCK exported

SERVER_VERSION = "ems-sim/1.0"
ACTION_LOG_SCHEMA = "microgrid-dispatch-outage.action-log/v1"
TRIAL_SCHEMA = "microgrid-dispatch-outage.trial/v1"
PRIVATE_DIR = "/var/ems/private"
READY_PATH = "/var/ems/ready"
EXPORT_PATH = "/var/ems/export/trial.json"
POOL_PATH = "/opt/ems/seeds.json"


def make_world(seed: int, observe: bool = True) -> World:
    return World(seed, observe=observe)


def _forecast(world, params, step) -> dict:
    p = world.p
    rows = []
    for h in range(72):
        rows.append({
            "hour": h,
            "pv_mw": round(model.pv_mw(p, h + 0.5, p["pv_shift_h"]) / p["pv_cloud"][(h // 24) % 4]
                           * 0.95, 3),
            "load_mw": {g: round(model.load_mw(p, g, h + 0.5, p["load_shift_h"]) / p["load_scale"][g], 3)
                        for g in GROUPS},
        })
    return {"issued_hour": 0, "hourly": rows}


def _messages(world, params, step) -> dict:
    hour = world.clock.hour(step)
    out = [m for m in terms.messages(world.p) if m["issued_hour"] <= hour]
    return {"plant_hour": round(hour, 4), "messages": out}


EXTRA_OPS = {"forecast": _forecast, "messages": _messages}
EXTRA_ROUTES = {("GET", "/api/v1/forecast"): "forecast", ("GET", "/api/v1/messages"): "messages"}


def collect(seed: int, action_log: dict) -> dict:
    import sys

    return grading.collect(sys.modules[__name__], seed, action_log)
