"""Condition evaluation (specification section 4).

A statement's conditions are joined with AND: the statement applies only when every
condition holds. Each condition is `{key, op, values}` read against the query context.
"""

from . import glob
from .errors import KindError, UnknownOperator

SCALAR_OPS = ("equals", "equalsFold", "glob", "numLt")
SET_OPS = ("anyOf", "allOf")


def fold(text: str) -> str:
    """Fold the twenty-six ASCII letters A-Z to lower case and nothing else."""
    return text.lower()


def _as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KindError("numLt needs a numeric value")
    return float(value)


def _kind(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def same(element, listed) -> bool:
    """Section 4 set equality: the same kind and the same value."""
    return _kind(element) == _kind(listed) and element == listed


def _context_entry(context, key):
    if key not in context:
        return "absent", []
    value = context[key]
    if isinstance(value, list):
        return "list", value
    return "scalar", [value]


def evaluate(condition, context) -> bool:
    op = condition["op"]
    values = condition["values"]
    kind, items = _context_entry(context, condition["key"])

    if op in SCALAR_OPS:
        if kind == "absent":
            return False
        if kind == "list":
            raise KindError(f"{op} needs a single value, not a list")
        return _scalar(op, items[0], values)

    if op in SET_OPS:
        members = items
        if op == "anyOf":
            return any(same(c, w) for c in members for w in values)
        # allOf: every context value is among the listed values.
        return bool(members) and all(any(same(c, w) for w in values) for c in members)

    raise UnknownOperator(f"no such condition operator {op!r}")


def _scalar(op, value, values) -> bool:
    if op == "numLt":
        left = _as_number(value)
        return any(left < _as_number(w) for w in values)
    if not isinstance(value, str):
        raise KindError(f"{op} needs a string value")
    if op == "equals":
        return any(value == w for w in values)
    if op == "equalsFold":
        return any(fold(value) == fold(w) for w in values if isinstance(w, str))
    if op == "glob":
        return any(glob.matches(w, value) for w in values if isinstance(w, str))
    raise UnknownOperator(f"no such condition operator {op!r}")
