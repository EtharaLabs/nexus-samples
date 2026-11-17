"""An independent evaluator for docs/DESIGN.md.

It borrows only the parser, the binder and the catalog loader from a pristine
baseline copy of the engine, and implements every semantic rule, three-valued
logic, collation, LIKE, the IN and NOT IN table, and ordering, on its own. It
shares no line with tarn/exec/expr.py, so a defect in the shipped expression
evaluator cannot hide from it. It applies no optimizer rule.
"""

from tarn import ast_nodes as A
from tarn import parse as P

import obind as B
from tarn.catalog import Catalog

NOCASE = "NOCASE"


class OracleTypeError(Exception):
    pass


def fold_ascii(text: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


def ckey(text: str, collation: str):
    return fold_ascii(text) if collation == NOCASE else text


def vkind(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, str):
        return "TEXT"
    raise OracleTypeError(repr(value))


def carried(expr):
    """The collation an operand carries, or None when it carries none.

    docs/DESIGN.md section 5: a bare column reference carries its declared
    collation, so a BINARY column carries BINARY; a literal carries none.
    """
    if isinstance(expr, A.Col):
        return expr.collation or "BINARY"
    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            got = carried(arg)
            if got is not None:
                return got
        return None
    if isinstance(expr, A.Case):
        for _, result in expr.whens:
            got = carried(result)
            if got is not None:
                return got
        return carried(expr.otherwise)
    return None


def collation_of(expr) -> str:
    got = carried(expr)
    return "BINARY" if got is None else got


def pair_collation(left, right) -> str:
    got = carried(left)
    if got is not None:
        return got
    got = carried(right)
    return got if got is not None else "BINARY"


def oeq(a, b, collation):
    if a is None or b is None:
        return None
    ka, kb = vkind(a), vkind(b)
    if ka == "TEXT" and kb == "TEXT":
        return ckey(a, collation) == ckey(b, collation)
    if ka == "BOOLEAN" or kb == "BOOLEAN":
        if ka != kb:
            raise OracleTypeError("boolean vs other")
        return a is b or a == b
    if ka in ("INTEGER", "REAL") and kb in ("INTEGER", "REAL"):
        return a == b
    raise OracleTypeError(f"{ka} vs {kb}")


def ocmp(a, b, collation):
    if a is None or b is None:
        return None
    ka, kb = vkind(a), vkind(b)
    if ka == "TEXT" and kb == "TEXT":
        x, y = ckey(a, collation), ckey(b, collation)
        return (x > y) - (x < y)
    if ka == "BOOLEAN" or kb == "BOOLEAN":
        if ka != kb:
            raise OracleTypeError("boolean vs other")
        x, y = int(a), int(b)
        return (x > y) - (x < y)
    if ka in ("INTEGER", "REAL") and kb in ("INTEGER", "REAL"):
        return (a > b) - (a < b)
    raise OracleTypeError(f"{ka} vs {kb}")


def olike(subject, pattern, collation):
    if subject is None or pattern is None:
        return None
    if collation == NOCASE:
        subject = fold_ascii(subject)
        pattern = fold_ascii(pattern)
    return _match(subject, 0, pattern, 0)


def _match(s: str, si: int, p: str, pi: int) -> bool:
    while pi < len(p):
        ch = p[pi]
        if ch == "%":
            for skip in range(si, len(s) + 1):
                if _match(s, skip, p, pi + 1):
                    return True
            return False
        if si >= len(s):
            return False
        if ch != "_" and s[si] != ch:
            return False
        si += 1
        pi += 1
    return si == len(s)


def oand(a, b):
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def oor(a, b):
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def onot(a):
    return None if a is None else (not a)


def okey(value, collation):
    if value is None:
        return (0,)
    if isinstance(value, str):
        return (1, ckey(value, collation))
    if isinstance(value, bool):
        return (1, int(value))
    return (1, value)


def oeval(expr, row, catalog):
    if isinstance(expr, A.Lit):
        return expr.value
    if isinstance(expr, A.Col):
        return row.get(expr.key)
    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            value = oeval(arg, row, catalog)
            if value is not None:
                return value
        return None
    if isinstance(expr, A.Case):
        for cond, result in expr.whens:
            if oeval(cond, row, catalog) is True:
                return oeval(result, row, catalog)
        return oeval(expr.otherwise, row, catalog)
    if isinstance(expr, A.Not):
        return onot(oeval(expr.operand, row, catalog))
    if isinstance(expr, A.IsNull):
        value = oeval(expr.operand, row, catalog)
        return (value is not None) if expr.negated else (value is None)
    if isinstance(expr, A.IsNotDistinct):
        left = oeval(expr.left, row, catalog)
        right = oeval(expr.right, row, catalog)
        if left is None and right is None:
            return True
        if left is None or right is None:
            return False
        return oeq(left, right, pair_collation(expr.left, expr.right))
    if isinstance(expr, A.Like):
        value = olike(
            oeval(expr.operand, row, catalog),
            oeval(expr.pattern, row, catalog),
            pair_collation(expr.operand, expr.pattern),
        )
        return onot(value) if expr.negated else value
    if isinstance(expr, A.InSubquery):
        left = oeval(expr.operand, row, catalog)
        values = [r[0] for r in evaluate_select(expr.select, catalog)[1]]
        if not values:
            inner = False
        else:
            selected = expr.select.items[0][0] if getattr(expr.select, "items", None) else None
            collation = pair_collation(expr.operand, selected)
            found = False
            saw_null = False
            for candidate in values:
                verdict = oeq(left, candidate, collation)
                if verdict is True:
                    found = True
                    break
                if verdict is None:
                    saw_null = True
            inner = True if found else (None if saw_null else False)
        return onot(inner) if expr.negated else inner
    if isinstance(expr, A.BinOp):
        op = expr.op
        if op == "and":
            return oand(oeval(expr.left, row, catalog), oeval(expr.right, row, catalog))
        if op == "or":
            return oor(oeval(expr.left, row, catalog), oeval(expr.right, row, catalog))
        left = oeval(expr.left, row, catalog)
        right = oeval(expr.right, row, catalog)
        if op in ("=", "<>", "<", "<=", ">", ">="):
            collation = pair_collation(expr.left, expr.right)
            if op == "=":
                return oeq(left, right, collation)
            if op == "<>":
                return onot(oeq(left, right, collation))
            verdict = ocmp(left, right, collation)
            if verdict is None:
                return None
            return {
                "<": verdict < 0,
                "<=": verdict <= 0,
                ">": verdict > 0,
                ">=": verdict >= 0,
            }[op]
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
                raise ZeroDivisionError("TARN-301")
            if vkind(left) == "INTEGER" and vkind(right) == "INTEGER":
                q = abs(left) // abs(right)
                return -q if (left < 0) != (right < 0) else q
            return left / right
    raise OracleTypeError(f"cannot evaluate {expr!r}")


def _rows_of(catalog, ref):
    table = catalog.table(ref.table)
    return [{f"{ref.alias}.{k}": v for k, v in row.items()} for row in table.rows]


def _keys_of(catalog, ref):
    table = catalog.table(ref.table)
    return [f"{ref.alias}.{c.name}" for c in table.columns]


def evaluate_select(select, catalog):
    rows = _rows_of(catalog, select.source)
    for join in select.joins:
        right_rows = _rows_of(catalog, join.table)
        right_keys = _keys_of(catalog, join.table)
        out = []
        for lrow in rows:
            matched = False
            for rrow in right_rows:
                merged = {**lrow, **rrow}
                if oeval(join.on, merged, catalog) is True:
                    out.append(merged)
                    matched = True
            if not matched and join.kind == "left":
                padded = dict(lrow)
                for key in right_keys:
                    padded[key] = None
                out.append(padded)
        rows = out

    if select.where is not None:
        rows = [r for r in rows if oeval(select.where, r, catalog) is True]

    for item in reversed(select.order_by):
        collation = collation_of(item.expr)
        rows.sort(
            key=lambda row, it=item, coll=collation: okey(
                oeval(it.expr, row, catalog), coll
            ),
            reverse=(item.direction == "desc"),
        )

    if select.limit is not None:
        rows = rows[: select.limit]

    columns = [alias for _, alias in select.items]
    data = [[oeval(e, row, catalog) for e, _ in select.items] for row in rows]
    return columns, data


def evaluate(database, sql: str):
    catalog = database if isinstance(database, Catalog) else Catalog.from_dict(database)
    select = B.bind(P.parse(sql), catalog)
    return evaluate_select(select, catalog)
