"""P5, answer. Section 7 says an index stores its rows in ASC order of the index
column under that column's collation. This engine orders a text index by raw code
point, ignoring the collation, so an index on a NOCASE column reads in the wrong
order. An index on an INTEGER column is unaffected."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """    if isinstance(value, str):
        return (1, T.collate_key(value, collation))"""
NEW = """    if isinstance(value, str):
        return (1, value)"""
raise SystemExit(patch("tarn/storage/index.py", OLD, NEW, "P5"))
