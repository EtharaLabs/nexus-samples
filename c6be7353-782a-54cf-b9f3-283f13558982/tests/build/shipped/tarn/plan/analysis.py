"""Shared plan analyses.

Several rules depend on the two predicates in this module, so a wrong answer here
"""
from .. import ast_nodes as A


def expr_columns(expr) -> set:
    """Every column key an expression references, as 'alias.column' strings."""
    if isinstance(expr, A.Col):
        return {expr.key}
    if isinstance(expr, A.Lit):
        return set()
    if isinstance(expr, A.BinOp):
        return expr_columns(expr.left) | expr_columns(expr.right)
    if isinstance(expr, A.Not):
        return expr_columns(expr.operand)
    if isinstance(expr, A.IsNull):
        return expr_columns(expr.operand)
    if isinstance(expr, A.IsNotDistinct):
        return expr_columns(expr.left) | expr_columns(expr.right)
    if isinstance(expr, A.Like):
        return expr_columns(expr.operand) | expr_columns(expr.pattern)
    if isinstance(expr, A.Coalesce):
        out = set()
        for arg in expr.args:
            out |= expr_columns(arg)
        return out
    if isinstance(expr, A.Case):
        out = expr_columns(expr.otherwise)
        for cond, result in expr.whens:
            out |= expr_columns(cond) | expr_columns(result)
        return out
    if isinstance(expr, A.InSubquery):
        return expr_columns(expr.operand)
    return set()


def split_and(expr) -> list:
    if expr is None:
        return []
    if isinstance(expr, A.BinOp) and expr.op == "and":
        return split_and(expr.left) + split_and(expr.right)
    return [expr]


def join_and(conjuncts: list):
    if not conjuncts:
        return None
    node = conjuncts[0]
    for extra in conjuncts[1:]:
        node = A.BinOp("and", node, extra)
    return node


def strict_in(expr, cols: set) -> bool:
    """True when `expr` evaluates to NULL whenever every column of `cols` is NULL."""
    if isinstance(expr, A.Col):
        return expr.key in cols
    if isinstance(expr, A.Lit):
        return expr.value is None
    if isinstance(expr, A.BinOp):
        if expr.op in ("and", "or"):
            return False
        return strict_in(expr.left, cols) or strict_in(expr.right, cols)
    if isinstance(expr, A.Coalesce):
        return all(strict_in(arg, cols) for arg in expr.args)
    if isinstance(expr, A.Like):
        return strict_in(expr.operand, cols) or strict_in(expr.pattern, cols)
    if isinstance(expr, A.InSubquery):
        return strict_in(expr.operand, cols)
    return False


def null_rejecting(expr, cols: set) -> bool:
    """True when `expr` cannot evaluate to TRUE once every column of `cols` is NULL."""
    if isinstance(expr, A.BinOp):
        if expr.op == "and":
            return null_rejecting(expr.left, cols) or null_rejecting(expr.right, cols)
        if expr.op == "or":
            return null_rejecting(expr.left, cols) and null_rejecting(expr.right, cols)
        if expr.op in ("=", "<>", "<", "<=", ">", ">="):
            return strict_in(expr.left, cols) or strict_in(expr.right, cols)
        return strict_in(expr, cols)
    if isinstance(expr, A.Col):
        return expr.key in cols
    if isinstance(expr, A.IsNull):
        return strict_in(expr.operand, cols) if expr.negated else False
    if isinstance(expr, A.Like):
        return strict_in(expr.operand, cols) or strict_in(expr.pattern, cols)
    if isinstance(expr, A.InSubquery):
        return strict_in(expr.operand, cols)
    return False


def not_null_columns(expr, candidates: set) -> set:
    """The subset of `candidates` a predicate proves non-NULL for every kept row."""
    proven = set()
    for conjunct in split_and(expr):
        for key in expr_columns(conjunct) & candidates:
            if null_rejecting(conjunct, {key}):
                proven.add(key)
    return proven
