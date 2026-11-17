"""Hash keys for the hash join build and probe sides.

key, and two values that do not must not.
"""
from .. import types as T


def join_key(value, collation: str = T.BINARY):
    """The hash-bucket key of a join column value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, (int, float)):
        # INTEGER and REAL share one bucket space: Python compares and hashes int
        # against float exactly, so 1 and 1.0 collide while 2**53+1 and 2.0**53 do not.
        return ("n", value)
    return ("t", T.collate_key(value, collation))
