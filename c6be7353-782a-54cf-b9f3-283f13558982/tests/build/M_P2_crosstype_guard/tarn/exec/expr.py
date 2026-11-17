"""Shared expression evaluator.

Every operator evaluates expressions through this module, so a value never depends
on which plan produced it.
"""
import re

from .. import ast_nodes as A
from .. import types as T


def carried_collation(expr):
    """The collation an operand carries, or None when it carries none.

    collation, so a column declared BINARY carries BINARY; a literal carries none.
    """
    if isinstance(expr, A.Col):
        return expr.collation or T.BINARY
    if isinstance(expr, A.Coalesce):
        return None
    if isinstance(expr, A.Case):
        for _, result in expr.whens:
            carried = carried_collation(result)
            if carried is not None:
                return carried
        return carried_collation(expr.otherwise)
    return None


def _collation_of(expr) -> str:
    carried = carried_collation(expr)
    return T.BINARY if carried is None else carried


def comparison_collation(left, right) -> str:
    carried = carried_collation(left)
    if carried is not None:
        return carried
    carried = carried_collation(right)
    if carried is not None:
        return carried
    return T.BINARY


def sql_eq(a, b, collation: str = T.BINARY):
    """Three-valued equality."""
    if a is None or b is None:
        return None
    ka, kb = T.kind(a), T.kind(b)
    if ka == T.TEXT and kb == T.TEXT:
        return T.collate_key(a, collation) == T.collate_key(b, collation)
    if ka == T.BOOLEAN or kb == T.BOOLEAN:
        if ka != kb:
            raise T.TypeMismatch(f"cannot compare {ka} with {kb}")
        return a == b
    if ka in T.NUMERIC_TYPES and kb in T.NUMERIC_TYPES:
        return a == b
    raise T.TypeMismatch(f"cannot compare {ka} with {kb}")


def sql_cmp(a, b, collation: str = T.BINARY):
    """Three-valued ordering comparison; returns -1, 0, 1 or None."""
    if a is None or b is None:
        return None
    ka, kb = T.kind(a), T.kind(b)
    if ka == T.TEXT and kb == T.TEXT:
        ca, cb = T.collate_key(a, collation), T.collate_key(b, collation)
        return (ca > cb) - (ca < cb)
    if ka == T.BOOLEAN or kb == T.BOOLEAN:
        if ka != kb:
            raise T.TypeMismatch(f"cannot compare {ka} with {kb}")
        ia, ib = int(a), int(b)
        return (ia > ib) - (ia < ib)
    if ka in T.NUMERIC_TYPES and kb in T.NUMERIC_TYPES:
        return (a > b) - (a < b)
    raise T.TypeMismatch(f"cannot compare {ka} with {kb}")


def _like_regex(pattern: str) -> str:
    out = ["(?s)"]
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def like_match(subject, pattern, collation: str = T.BINARY):
    """SQL LIKE. `%` matches any run of characters and `_` matches exactly one."""
    if subject is None or pattern is None:
        return None
    if collation == T.NOCASE:
        subject = T.ascii_fold(subject)
        pattern = T.ascii_fold(pattern)
    return re.fullmatch(_like_regex(pattern), subject) is not None


def and3(a, b):
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or3(a, b):
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not3(a):
    if a is None:
        return None
    return not a


def truthy(value) -> bool:
    """A WHERE or ON clause keeps a row only when the predicate is exactly TRUE."""
    return value is True


def eval_expr(expr, row, subquery=None):
    """Evaluate `expr` against `row`.

    `subquery` is a callable taking an ast_nodes.Select and returning the list of
    first-column values it produces; it is only needed for IN and NOT IN.
    """
    if isinstance(expr, A.Lit):
        return expr.value
    if isinstance(expr, A.Col):
        return row.get(expr.key)
    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            value = eval_expr(arg, row, subquery)
            if value is not None:
                return value
        return None
    if isinstance(expr, A.Case):
        for cond, result in expr.whens:
            if truthy(eval_expr(cond, row, subquery)):
                return eval_expr(result, row, subquery)
        return eval_expr(expr.otherwise, row, subquery)
    if isinstance(expr, A.Not):
        return not3(eval_expr(expr.operand, row, subquery))
    if isinstance(expr, A.IsNull):
        value = eval_expr(expr.operand, row, subquery)
        return (value is not None) if expr.negated else (value is None)
    if isinstance(expr, A.IsNotDistinct):
        left = eval_expr(expr.left, row, subquery)
        right = eval_expr(expr.right, row, subquery)
        if left is None and right is None:
            return True
        if left is None or right is None:
            return False
        return sql_eq(left, right, comparison_collation(expr.left, expr.right))
    if isinstance(expr, A.Like):
        subject = eval_expr(expr.operand, row, subquery)
        pattern = eval_expr(expr.pattern, row, subquery)
        result = like_match(
            subject, pattern, comparison_collation(expr.operand, expr.pattern)
        )
        return not3(result) if expr.negated else result
    if isinstance(expr, A.InSubquery):
        if subquery is None:
            raise T.TarnError("IN requires a subquery runner")
        value = eval_expr(expr.operand, row, subquery)
        values = subquery(expr.select)
        if not values:
            # An empty right side: IN is FALSE and NOT IN is TRUE for any left
            # value, NULL included.
            return True if expr.negated else False
        found = False
        saw_null = False
        selected = (
            expr.select.items[0][0] if getattr(expr.select, "items", None) else None
        )
        in_collation = comparison_collation(expr.operand, selected)
        for candidate in values:
            cmp = sql_eq(value, candidate, in_collation)
            if cmp is True:
                found = True
                break
            if cmp is None:
                saw_null = True
        if found:
            inner = True
        elif saw_null:
            inner = None
        else:
            inner = False
        return not3(inner) if expr.negated else inner
    if isinstance(expr, A.BinOp):
        op = expr.op
        if op == "and":
            return and3(
                eval_expr(expr.left, row, subquery),
                eval_expr(expr.right, row, subquery),
            )
        if op == "or":
            return or3(
                eval_expr(expr.left, row, subquery),
                eval_expr(expr.right, row, subquery),
            )
        left = eval_expr(expr.left, row, subquery)
        right = eval_expr(expr.right, row, subquery)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            collation = comparison_collation(expr.left, expr.right)
            if op == "=":
                return sql_eq(left, right, collation)
            if op == "<>":
                return not3(sql_eq(left, right, collation))
            cmp = sql_cmp(left, right, collation)
            if cmp is None:
                return None
            if op == "<":
                return cmp < 0
            if op == "<=":
                return cmp <= 0
            if op == ">":
                return cmp > 0
            return cmp >= 0
        if left is None or right is None:
            return None
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise T.DivisionByZero("division by zero")
            if T.kind(left) == T.INTEGER and T.kind(right) == T.INTEGER:
                quotient = abs(left) // abs(right)
                return -quotient if (left < 0) != (right < 0) else quotient
            return left / right
        raise T.TarnError(f"unknown operator {op}")
    raise T.TarnError(f"cannot evaluate {expr!r}")
