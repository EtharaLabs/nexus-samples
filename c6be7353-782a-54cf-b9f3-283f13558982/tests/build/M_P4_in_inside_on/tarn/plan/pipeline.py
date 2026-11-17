"""Rule order, the rule registry, and physical plan construction. the rules run in. Every rule is
semantics preserving on its own, so disabling any subset must not change an answer.
"""
from .. import ast_nodes as A
from ..exec import operators as O
from ..storage.index import SortedIndex
from . import joinorder, nodes as N
from .rules import fold, notin, outer_join, pushdown, sortelim

RULES = [
    (fold.NAME, fold.apply),
    (notin.NAME, notin.apply),
    (outer_join.NAME, outer_join.apply),
    (pushdown.NAME, pushdown.apply),
    (sortelim.NAME, sortelim.apply),
]

RULE_NAMES = [name for name, _ in RULES]


class Ctx:
    def __init__(self, catalog, scope) -> None:
        self.catalog = catalog
        self.scope = scope
        self.alias_tables: dict = {}
        for alias, table in getattr(scope, "aliases", {}).items():
            self.alias_tables[alias] = table

    def register_plan(self, node) -> None:
        if isinstance(node, N.LScan) and node.alias not in self.alias_tables:
            self.alias_tables[node.alias] = self.catalog.table(node.table)
        for child in N.children(node):
            self.register_plan(child)

    def columns_of(self, aliases) -> set:
        out = set()
        for alias in aliases:
            table = self.alias_tables.get(alias)
            if table is None:
                continue
            out |= {f"{alias}.{col.name}" for col in table.columns}
        return out


def build_logical(select) -> object:
    node = N.LScan(select.source.table, select.source.alias)
    for join in select.joins:
        right = N.LScan(join.table.table, join.table.alias)
        node = N.LJoin(kind=join.kind, left=node, right=right, on=join.on)
    if select.where is not None:
        node = N.LFilter(node, select.where)
    if select.order_by:
        node = N.LSort(node, list(select.order_by))
    if select.limit is not None:
        node = N.LLimit(node, select.limit)
    return N.LProject(node, list(select.items))


def optimize(plan, ctx, disabled=frozenset()):
    ctx.register_plan(plan)
    for name, rule in RULES:
        if name in disabled:
            continue
        plan = rule(plan, ctx)
        ctx.register_plan(plan)
    joinorder.choose(plan, ctx)
    return plan


def build_physical(node, ctx, stats, subquery=None):
    op = _build(node, ctx, stats, subquery)
    op.subquery = subquery
    return op


def _build(node, ctx, stats, subquery=None):
    if isinstance(node, N.LScan):
        table = ctx.catalog.table(node.table)
        if node.index_column:
            index = SortedIndex(table, node.index_column)
            return O.IndexScan(table, node.alias, index, stats)
        return O.SeqScan(table, node.alias, stats)
    if isinstance(node, N.LFilter):
        return O.Filter(
            build_physical(node.child, ctx, stats, subquery), node.pred, stats, subquery
        )
    if isinstance(node, N.LJoin):
        left = build_physical(node.left, ctx, stats, subquery)
        right = build_physical(node.right, ctx, stats, subquery)
        right_keys = sorted(ctx.columns_of(N.scan_aliases(node.right)))
        if node.physical == "merge":
            return O.MergeJoin(left, right, node.on.left, node.on.right, stats,
                           collation=node.key_collation)
        if node.physical == "hash":
            return O.HashJoin(
                left, right, node.on.left, node.on.right, node.kind, right_keys,
                stats, collation=node.key_collation
            )
        return O.NestedLoopJoin(left, right, node.on, node.kind, right_keys, stats)
    if isinstance(node, N.LAntiJoin):
        return O.AntiJoin(
            build_physical(node.left, ctx, stats, subquery),
            build_physical(node.right, ctx, stats, subquery),
            node.left_expr,
            node.right_expr,
            node.null_aware,
            stats,
        )
    if isinstance(node, N.LAntiMatch):
        return O.AntiMatch(
            build_physical(node.left, ctx, stats, subquery),
            build_physical(node.right, ctx, stats, subquery),
            node.on,
            stats,
        )
    if isinstance(node, N.LNullPad):
        return O.NullPad(
            build_physical(node.child, ctx, stats, subquery), node.pad_keys, stats
        )
    if isinstance(node, N.LUnionAll):
        return O.UnionAll(
            build_physical(node.left, ctx, stats, subquery),
            build_physical(node.right, ctx, stats, subquery),
            stats,
        )
    if isinstance(node, N.LSort):
        return O.Sort(
            build_physical(node.child, ctx, stats, subquery), node.keys, stats
        )
    if isinstance(node, N.LLimit):
        return O.Limit(
            build_physical(node.child, ctx, stats, subquery), node.count, stats
        )
    if isinstance(node, N.LProject):
        return O.Project(
            build_physical(node.child, ctx, stats, subquery),
            node.items,
            stats,
            subquery,
        )
    raise TypeError(f"cannot build {node!r}")
