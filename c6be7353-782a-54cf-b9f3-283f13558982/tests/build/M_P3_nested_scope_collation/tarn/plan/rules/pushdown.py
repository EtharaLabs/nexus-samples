"""Predicate pushdown."""
from .. import nodes as N
from ..analysis import expr_columns, join_and, split_and

NAME = "pushdown"


def apply(plan, ctx):
    return _walk(plan, ctx)


def _walk(node, ctx):
    if isinstance(node, N.LFilter):
        node.child = _walk(node.child, ctx)
        return _push(node, ctx)
    if isinstance(node, (N.LJoin, N.LUnionAll, N.LAntiJoin, N.LAntiMatch)):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, (N.LNullPad, N.LSort, N.LLimit, N.LProject)):
        node.child = _walk(node.child, ctx)
        return node
    return node


def _push(filt, ctx):
    join = filt.child
    if not isinstance(join, N.LJoin):
        return filt
    left_cols = ctx.columns_of(N.scan_aliases(join.left))
    right_cols = ctx.columns_of(N.scan_aliases(join.right))
    keep, to_left, to_right = [], [], []
    for conjunct in split_and(filt.pred):
        cols = expr_columns(conjunct)
        if cols and cols <= left_cols:
            to_left.append(conjunct)
        elif cols and cols <= right_cols and join.kind == "inner":
            to_right.append(conjunct)
        else:
            keep.append(conjunct)
    if not to_left and not to_right:
        return filt
    if to_left:
        join.left = N.LFilter(join.left, join_and(to_left))
    if to_right:
        join.right = N.LFilter(join.right, join_and(to_right))
    remaining = join_and(keep)
    return N.LFilter(join, remaining) if remaining is not None else join
