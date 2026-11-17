"""NOT IN rewritten as an anti-join."""
from ... import ast_nodes as A
from .. import nodes as N
from ..analysis import join_and, not_null_columns, split_and

NAME = "notin"


def apply(plan, ctx):
    return _walk(plan, ctx)


def _walk(node, ctx):
    if isinstance(node, N.LFilter):
        node.child = _walk(node.child, ctx)
        return _rewrite(node, ctx)
    for attr in ("child",):
        if hasattr(node, attr) and getattr(node, attr) is not None:
            setattr(node, attr, _walk(getattr(node, attr), ctx))
    for attr in ("left", "right"):
        if hasattr(node, attr):
            setattr(node, attr, _walk(getattr(node, attr), ctx))
    return node


def _simple_subquery(sub):
    if sub is None or sub.joins or sub.order_by or sub.limit is not None:
        return None
    if len(sub.items) != 1:
        return None
    expr = sub.items[0][0]
    if not isinstance(expr, A.Col):
        return None
    return expr


def _rewrite(filt, ctx):
    conjuncts = split_and(filt.pred)
    rest = []
    node = filt.child
    for conjunct in conjuncts:
        if isinstance(conjunct, A.InSubquery) and conjunct.negated:
            right_col = _simple_subquery(conjunct.select)
            if right_col is not None:
                node = _build_anti(node, conjunct, right_col, ctx)
                continue
        rest.append(conjunct)
    if node is filt.child:
        return filt
    remaining = join_and(rest)
    return N.LFilter(node, remaining) if remaining is not None else node


def _build_anti(child, conjunct, right_col, ctx):
    sub = conjunct.select
    right_plan = N.LScan(sub.source.table, sub.source.alias)
    if sub.where is not None:
        right_plan = N.LFilter(right_plan, sub.where)

    declared_nullable = (
        ctx.catalog.table(sub.source.table).column(right_col.name).nullable
    )
    proven = not_null_columns(sub.where, {right_col.key})
    right_nullable = declared_nullable and right_col.key not in proven

    return N.LAntiJoin(
        left=child,
        right=right_plan,
        left_expr=conjunct.operand,
        right_expr=right_col,
        null_aware=right_nullable,
    )
