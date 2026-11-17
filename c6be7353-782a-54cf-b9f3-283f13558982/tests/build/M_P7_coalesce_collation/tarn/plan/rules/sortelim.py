"""Sort elimination through an ordered index."""
from ... import ast_nodes as A
from .. import nodes as N

NAME = "sortelim"


def apply(plan, ctx):
    return _walk(plan, ctx)


def _walk(node, ctx):
    if isinstance(node, N.LSort):
        node.child = _walk(node.child, ctx)
        return _eliminate(node, ctx)
    if isinstance(node, (N.LJoin, N.LUnionAll, N.LAntiJoin, N.LAntiMatch)):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, (N.LFilter, N.LNullPad, N.LLimit, N.LProject)):
        node.child = _walk(node.child, ctx)
        return node
    return node


def _scan_of(node):
    if isinstance(node, N.LScan):
        return node
    if isinstance(node, N.LFilter):
        return _scan_of(node.child)
    return None


def _eliminate(sort, ctx):
    if len(sort.keys) != 1:
        return sort
    item = sort.keys[0]
    if item.direction != "asc" or not isinstance(item.expr, A.Col):
        return sort
    scan = _scan_of(sort.child)
    if scan is None or scan.alias != item.expr.alias:
        return sort
    index = ctx.catalog.index_for(scan.table, item.expr.name)
    if index is None:
        return sort
    column = ctx.catalog.table(scan.table).column(item.expr.name)
    if column.collation != (item.expr.collation or column.collation):
        return sort
    scan.index_column = column.name
    return sort.child
