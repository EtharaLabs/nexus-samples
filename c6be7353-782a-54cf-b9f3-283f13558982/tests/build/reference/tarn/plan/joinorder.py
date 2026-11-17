"""Physical join selection.

Selection is a function of input size and available index order alone; the key
types never take part in the choice.
"""
from .. import ast_nodes as A
from ..exec import expr as E
from . import nodes as N

HASH_BUILD_THRESHOLD = 8


def equi_keys(on):
    if (
        isinstance(on, A.BinOp)
        and on.op == "="
        and isinstance(on.left, A.Col)
        and isinstance(on.right, A.Col)
    ):
        return on.left, on.right
    return None


def _estimate(node, ctx) -> int:
    if isinstance(node, N.LScan):
        return len(ctx.catalog.table(node.table).rows)
    if isinstance(node, N.LFilter):
        return _estimate(node.child, ctx)
    if isinstance(node, (N.LJoin, N.LUnionAll)):
        return _estimate(node.left, ctx) + _estimate(node.right, ctx)
    for attr in ("child", "left"):
        if hasattr(node, attr):
            return _estimate(getattr(node, attr), ctx)
    return 1


def _indexed_scan(node, col, ctx):
    if not isinstance(node, N.LScan) or node.alias != col.alias:
        return None
    return ctx.catalog.index_for(node.table, col.name)


def choose(node, ctx):
    for child in N.children(node):
        choose(child, ctx)
    if not isinstance(node, N.LJoin):
        return node
    keys = equi_keys(node.on)
    if keys is None:
        node.physical = "nested"
        return node
    left_key, right_key = keys
    # Record the collation of the predicate as written. Lining the keys up with the
    # operand decides the collation, so the swap must not be allowed to change it.
    node.key_collation = E.comparison_collation(node.on.left, node.on.right)
    left_aliases = N.scan_aliases(node.left)
    right_aliases = N.scan_aliases(node.right)
    if left_key.alias not in left_aliases:
        left_key, right_key = right_key, left_key
    # An equality operator is only a join key when one side comes from each input.
    # `ON a.x = a.y` compares two columns of the same input, so no hash or merge
    # join can answer it: the other input supplies neither column.
    if left_key.alias not in left_aliases or right_key.alias not in right_aliases:
        node.physical = "nested"
        return node

    if node.kind == "inner":
        left_index = _indexed_scan(node.left, left_key, ctx)
        right_index = _indexed_scan(node.right, right_key, ctx)
        same_shape = (
            left_index is not None
            and right_index is not None
            and left_key.type == right_key.type
            and left_key.collation == right_key.collation
        )
        if same_shape:
            node.left.index_column = left_key.name
            node.right.index_column = right_key.name
            node.physical = "merge"
            node.on = A.BinOp("=", left_key, right_key)
            return node

    if _estimate(node.right, ctx) >= HASH_BUILD_THRESHOLD:
        node.physical = "hash"
        node.on = A.BinOp("=", left_key, right_key)
        return node
    node.physical = "nested"
    return node
