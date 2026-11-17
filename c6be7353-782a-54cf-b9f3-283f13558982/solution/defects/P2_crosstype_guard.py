"""P2, plan only. Section 8 chooses the join implementation from input size and
available index order alone, and the kinds of the keys take no part. This engine
routes an INTEGER to REAL equality join to a nested loop however large the build
side is, so a hash join that section 8 requires never appears."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """    if _estimate(node.right, ctx) >= HASH_BUILD_THRESHOLD:"""
NEW = """    if left_key.type != right_key.type:
        node.physical = "nested"
        return node
    if _estimate(node.right, ctx) >= HASH_BUILD_THRESHOLD:"""
raise SystemExit(patch("tarn/plan/joinorder.py", OLD, NEW, "P2"))
