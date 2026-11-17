"""Constant folding.

Folding evaluates a constant subtree through the shared evaluator, so a folded
expression always carries the same three-valued result as the unfolded one.
"""
from ... import ast_nodes as A
from ...exec import expr as E
from .. import nodes as N

NAME = "fold"


def apply(plan, ctx):
    return _walk(plan, ctx)


def _walk(node, ctx):
    if isinstance(node, N.LFilter):
        node.child = _walk(node.child, ctx)
        node.pred = fold_expr(node.pred)
        return node
    if isinstance(node, N.LJoin):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        node.on = fold_expr(node.on)
        return node
    if isinstance(node, (N.LUnionAll, N.LAntiJoin, N.LAntiMatch)):
        node.left = _walk(node.left, ctx)
        node.right = _walk(node.right, ctx)
        return node
    if isinstance(node, N.LProject):
        node.child = _walk(node.child, ctx)
        node.items = [(fold_expr(e), alias) for e, alias in node.items]
        return node
    if isinstance(node, (N.LNullPad, N.LSort, N.LLimit)):
        node.child = _walk(node.child, ctx)
        return node
    return node


def _is_const(expr) -> bool:
    if isinstance(expr, A.Lit):
        return True
    if isinstance(expr, A.BinOp):
        return _is_const(expr.left) and _is_const(expr.right)
    if isinstance(expr, A.Not):
        return _is_const(expr.operand)
    if isinstance(expr, A.Coalesce):
        return all(_is_const(a) for a in expr.args)
    return False


def fold_expr(expr):
    if expr is None:
        return None
    if isinstance(expr, A.Lit):
        return expr
    if isinstance(expr, A.BinOp):
        expr.left = fold_expr(expr.left)
        expr.right = fold_expr(expr.right)
    elif isinstance(expr, A.Not):
        expr.operand = fold_expr(expr.operand)
    elif isinstance(expr, A.Coalesce):
        expr.args = [fold_expr(a) for a in expr.args]
    if _is_const(expr) and not isinstance(expr, A.Lit):
        try:
            return A.Lit(E.eval_expr(expr, {}))
        except Exception:
            return expr
    return expr
