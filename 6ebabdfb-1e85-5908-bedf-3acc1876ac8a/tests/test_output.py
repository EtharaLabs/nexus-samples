"""Compiled items, read from the grade.json that tests/grade.py writes and tests/test.sh
places beside this file before Reward Kit runs.

Twelve items credit the twelve defects by attribution over single-fix variants; eight more
check minimality in structure, data and request, reproduction, boundary, boundary on
both axes, and that each finding's expected and observed outputs are right. A false
finding zeroes every item inside grade.py. reward.toml aggregates them with all-pass.
"""

import json
from pathlib import Path

import rewardkit
from rewardkit import criterion

PARAMS = json.loads('{"compiled": [["P1_index_drops_qmark", 1], ["P2_specificity_length", 1], ["P3_depth_before_effect", 1], ["P4_allof_not_vacuous", 1], ["P5_closure_deepest", 1], ["P6_fold_unicode", 1], ["P7_notaction_specificity", 1], ["P8_explain_tiebreak", 1], ["P9_condition_short_circuit", 1], ["P10_index_dedup_trace", 1], ["P11_numlt_float", 1], ["P12_anyof_stringify", 1], ["minimal_structure", 1], ["minimal_data", 1], ["minimal_request", 1], ["reproduced", 1], ["bounded", 1], ["bounded_both_axes", 1], ["expected_correct", 1], ["observed_correct", 1]]}')


GRADE = Path(__file__).resolve().parent / "grade.json"


def _item(name: str) -> float:
    report = json.loads(GRADE.read_text())
    return float(report["items"][name])


@criterion(shared=True)
def P1_index_drops_qmark(workspace: Path) -> float:
    return _item("P1_index_drops_qmark")


@criterion(shared=True)
def P2_specificity_length(workspace: Path) -> float:
    return _item("P2_specificity_length")


@criterion(shared=True)
def P3_depth_before_effect(workspace: Path) -> float:
    return _item("P3_depth_before_effect")


@criterion(shared=True)
def P4_allof_not_vacuous(workspace: Path) -> float:
    return _item("P4_allof_not_vacuous")


@criterion(shared=True)
def P5_closure_deepest(workspace: Path) -> float:
    return _item("P5_closure_deepest")


@criterion(shared=True)
def P6_fold_unicode(workspace: Path) -> float:
    return _item("P6_fold_unicode")


@criterion(shared=True)
def P7_notaction_specificity(workspace: Path) -> float:
    return _item("P7_notaction_specificity")


@criterion(shared=True)
def P8_explain_tiebreak(workspace: Path) -> float:
    return _item("P8_explain_tiebreak")


@criterion(shared=True)
def P9_condition_short_circuit(workspace: Path) -> float:
    return _item("P9_condition_short_circuit")


@criterion(shared=True)
def P10_index_dedup_trace(workspace: Path) -> float:
    return _item("P10_index_dedup_trace")


@criterion(shared=True)
def P11_numlt_float(workspace: Path) -> float:
    return _item("P11_numlt_float")


@criterion(shared=True)
def P12_anyof_stringify(workspace: Path) -> float:
    return _item("P12_anyof_stringify")


@criterion(shared=True)
def minimal_structure(workspace: Path) -> float:
    return _item("minimal_structure")


@criterion(shared=True)
def minimal_data(workspace: Path) -> float:
    return _item("minimal_data")


@criterion(shared=True)
def minimal_request(workspace: Path) -> float:
    return _item("minimal_request")


@criterion(shared=True)
def reproduced(workspace: Path) -> float:
    return _item("reproduced")


@criterion(shared=True)
def bounded(workspace: Path) -> float:
    return _item("bounded")


@criterion(shared=True)
def bounded_both_axes(workspace: Path) -> float:
    return _item("bounded_both_axes")


@criterion(shared=True)
def expected_correct(workspace: Path) -> float:
    return _item("expected_correct")


@criterion(shared=True)
def observed_correct(workspace: Path) -> float:
    return _item("observed_correct")


for _id, _weight in PARAMS["compiled"]:
    getattr(rewardkit, _id)(weight=_weight, name=_id)
