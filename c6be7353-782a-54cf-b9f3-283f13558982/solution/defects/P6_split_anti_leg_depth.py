"""P6, answer, depth. Section 6.3 says the anti-join leg of the null-tolerant split
reads the unfiltered right input. This engine reads the filtered one when the
preserved side is itself a join, so a left row whose partners all fail the predicate
is reported as unmatched. With two tables the split is correct."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """    unmatched = N.LAntiMatch(join.left, join.right, join.on)"""
NEW = """    deep = isinstance(join.left, N.LJoin)
    unmatched = N.LAntiMatch(join.left, right_pushed if deep else join.right, join.on)"""
raise SystemExit(patch("tarn/plan/rules/outer_join.py", OLD, NEW, "P6"))
