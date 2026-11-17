"""Compiled items O1-O5, read from the grade tests/grade.py wrote before Reward Kit runs.

O1-O4 come from the scada-sim collect step, which replays the sidecar's action log from the trial
seed (deterministic simulator, unpaced) and scores 0 or 1; O5 scores the incident report against
the seed's expected set, a float in [0, 1].
"""

import json
from pathlib import Path

import rewardkit
from rewardkit import criterion

PARAMS = json.loads('{"compiled": [["O1", 5], ["O2", 5], ["O3", 3], ["O4", 3], ["O5", 5]], "grade": "/logs/verifier/grade.json"}')


def _grade() -> dict:
    return json.loads(Path(PARAMS["grade"]).read_text())


def _plant(item):
    """Rule C: a contract check counts only when the incident report is fully correct."""
    g = _grade()
    return float(g[item]) if float(g["O5"]) == 1.0 else 0.0


@criterion(shared=True)
def O1(workspace: Path) -> float:
    return _plant("O1")


@criterion(shared=True)
def O2(workspace: Path) -> float:
    return _plant("O2")


@criterion(shared=True)
def O3(workspace: Path) -> float:
    return _plant("O3")


@criterion(shared=True)
def O4(workspace: Path) -> float:
    return _plant("O4")


@criterion(shared=True)
def O5(workspace: Path) -> float:
    return float(_grade()["O5"])


for _id, _weight in PARAMS["compiled"]:
    getattr(rewardkit, _id)(weight=_weight, name=_id)
