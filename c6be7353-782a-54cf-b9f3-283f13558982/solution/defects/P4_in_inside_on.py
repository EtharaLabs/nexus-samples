"""P4, error, nesting. Section 2 permits IN in any expression, so a join condition
may hold one. This engine does not give the join operator the means to run a
subquery, so an IN inside ON raises TARN-000 where rows are required. An IN in a
WHERE clause is unaffected."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """                if E.truthy(E.eval_expr(self.on, combined, self.subquery)):"""
NEW = """                if E.truthy(E.eval_expr(self.on, combined)):"""
raise SystemExit(patch("tarn/exec/operators.py", OLD, NEW, "P4"))
