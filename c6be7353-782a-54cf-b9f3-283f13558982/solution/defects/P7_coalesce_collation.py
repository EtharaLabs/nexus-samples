"""P7, answer. Section 5 says COALESCE carries the collation of the first of its
arguments that carries one. This engine treats COALESCE as carrying none, so a
comparison or a LIKE whose operand is a COALESCE over a NOCASE column compares under
the default collation. A bare column operand is unaffected."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            carried = carried_collation(arg)
            if carried is not None:
                return carried
        return None"""
NEW = """    if isinstance(expr, A.Coalesce):
        return None"""
raise SystemExit(patch("tarn/exec/expr.py", OLD, NEW, "P7"))
