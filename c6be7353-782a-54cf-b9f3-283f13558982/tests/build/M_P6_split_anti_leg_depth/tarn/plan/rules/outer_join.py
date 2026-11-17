"""Outer-join simplification and the null-tolerant split."""
from ... import ast_nodes as A
from .. import nodes as N
from ..analysis import expr_columns, join_and, null_rejecting, split_and

NAME = "outer_join"


def apply(plan, ctx):
    return _walk(plan, ctx)


def _walk(node, ctx):
    if isinstance(node, N.LFilter):
        node.child = _walk(node.child, ctx)
        if isinstance(node.child, N.LJoin) and node.child.kind == "left":
            return _rewrite(node, ctx)
        return node
    if isinstance(node, N.LJoin):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, N.LUnionAll):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, (N.LAntiJoin, N.LAntiMatch)):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, (N.LNullPad, N.LSort, N.LLimit, N.LProject)):
        node.child = _walk(node.child, ctx)
        return node
    return node


def _convert_inner_joins(filt, ctx) -> None:
    """Apply the section 6.3 conversion test to every LEFT join below the filter."""
    conjuncts = split_and(filt.pred)
    node = filt.child
    while isinstance(node, N.LJoin):
        inner = node.left
        if isinstance(inner, N.LJoin) and inner.kind == "left":
            null_side = ctx.columns_of(N.scan_aliases(inner.right))
            touching = [c for c in conjuncts if expr_columns(c) & null_side]
            if any(null_rejecting(c, null_side) for c in touching):
                inner.kind = "inner"
        node = inner


def _rewrite(filt, ctx):
    join = filt.child
    null_side = ctx.columns_of(N.scan_aliases(join.right))
    conjuncts = split_and(filt.pred)
    touching = [c for c in conjuncts if expr_columns(c) & null_side]
    if not touching:
        return filt

    if any(null_rejecting(conjunct, null_side) for conjunct in touching):
        join.kind = "inner"
        return filt

    null_only = [c for c in touching if expr_columns(c) <= null_side]
    right_pushed = join.right
    if null_only:
        right_pushed = N.LFilter(join.right, join_and(null_only))

    inner_leg = N.LFilter(N.LJoin("inner", join.left, right_pushed, join.on), filt.pred)
    unmatched = N.LAntiMatch(join.left, join.right, join.on)
    pad_leg = N.LFilter(N.LNullPad(unmatched, sorted(null_side)), filt.pred)
    return N.LUnionAll(inner_leg, pad_leg)
