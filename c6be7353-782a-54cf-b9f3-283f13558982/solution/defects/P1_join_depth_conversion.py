"""P1, plan only, depth. Section 6.3 applies the inner-join conversion test to each
LEFT join beneath the WHERE. This engine tests only the join the WHERE sits directly
above, so with three or more joins an inner LEFT join that a null-rejecting conjunct
should convert stays an outer join. Answers are unchanged; the plan is not."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """        _convert_inner_joins(node, ctx)
"""
NEW = ""
raise SystemExit(patch("tarn/plan/rules/outer_join.py", OLD, NEW, "P1"))
