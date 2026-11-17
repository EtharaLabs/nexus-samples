"""Compiled items read from grade.json: one per planted defect, and five on the report.

The five report items are the three minimality checks (rows, schema, statement), the
reproduction check and the boundary check. reward.toml aggregates them with all-pass,
so the trial passes only when every one of the twelve holds.
"""

import json
from pathlib import Path

import rewardkit
from rewardkit import criterion

PARAMS = json.loads(
    '{"compiled": [["P1", 1], ["P2", 1], ["P3", 1], ["P4", 1], ["P5", 1], ["P6", 1],'
    ' ["P7", 1], ["rows_minimal", 1], ["schema_minimal", 1], ["statement_minimal", 1],'
    ' ["reproduced", 1], ["boundary_shown", 1]], "grade": "/logs/verifier/grade.json"}'
)

ITEMS = {
    "P1": "P1_join_depth_conversion",
    "P2": "P2_crosstype_guard",
    "P3": "P3_nested_scope_collation",
    "P4": "P4_in_inside_on",
    "P5": "P5_nocase_index_order",
    "P6": "P6_split_anti_leg_depth",
    "P7": "P7_coalesce_collation",
    "rows_minimal": "rows_minimal",
    "schema_minimal": "schema_minimal",
    "statement_minimal": "statement_minimal",
    "reproduced": "reproduced",
    "boundary_shown": "boundary_shown",
}


def _item(short: str) -> float:
    report = json.loads(Path(PARAMS["grade"]).read_text())
    return float(report["items"][ITEMS[short]])


@criterion(shared=True)
def P1(workspace: Path) -> float:
    return _item("P1")


@criterion(shared=True)
def P2(workspace: Path) -> float:
    return _item("P2")


@criterion(shared=True)
def P3(workspace: Path) -> float:
    return _item("P3")


@criterion(shared=True)
def P4(workspace: Path) -> float:
    return _item("P4")


@criterion(shared=True)
def P5(workspace: Path) -> float:
    return _item("P5")


@criterion(shared=True)
def P6(workspace: Path) -> float:
    return _item("P6")


@criterion(shared=True)
def P7(workspace: Path) -> float:
    return _item("P7")


@criterion(shared=True)
def rows_minimal(workspace: Path) -> float:
    return _item("rows_minimal")


@criterion(shared=True)
def schema_minimal(workspace: Path) -> float:
    return _item("schema_minimal")


@criterion(shared=True)
def statement_minimal(workspace: Path) -> float:
    return _item("statement_minimal")


@criterion(shared=True)
def reproduced(workspace: Path) -> float:
    return _item("reproduced")


@criterion(shared=True)
def boundary_shown(workspace: Path) -> float:
    return _item("boundary_shown")


for _id, _weight in PARAMS["compiled"]:
    getattr(rewardkit, _id)(weight=_weight, name=_id)
