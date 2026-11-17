"""The verifier's own name resolution and type checking.

The oracle used to borrow the engine's binder, which meant a defect in the
annotations the binder attaches, a column's collation or its declared kind, reached
the oracle and the engine alike and so could not be seen. This module resolves every
column reference itself, straight from the catalog, and implements sections 3, 5 and
10 on its own. Only the parser is still shared, because syntax carries no semantics.
"""

from tarn import ast_nodes as A

NUMERIC = ("INTEGER", "REAL")


class BindError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class Scope:
    def __init__(self, catalog) -> None:
        self.catalog = catalog
        self.aliases: dict = {}
        self.order: list = []
        self.null_supplying: set = set()

    def add(self, ref, null_supplying: bool = False) -> None:
        try:
            table = self.catalog.table(ref.table)
        except Exception:
            raise BindError("TARN-200", f"no such table {ref.table}") from None
        if ref.alias in self.aliases:
            raise BindError("TARN-202", f"duplicate alias {ref.alias}")
        self.aliases[ref.alias] = table
        self.order.append(ref.alias)
        if null_supplying:
            self.null_supplying.add(ref.alias)

    def resolve(self, col):
        if col.qualifier is not None:
            table = self.aliases.get(col.qualifier)
            if table is None:
                raise BindError("TARN-200", f"no such table alias {col.qualifier}")
            column = self._column(table, col.name)
            col.alias = col.qualifier
        else:
            hits = [(a, t) for a, t in self.aliases.items() if self._has(t, col.name)]
            if not hits:
                raise BindError("TARN-201", f"no such column {col.name}")
            if len(hits) > 1:
                raise BindError("TARN-202", f"column {col.name} is ambiguous")
            col.alias, table = hits[0]
            column = self._column(table, col.name)
        col.name = column.name
        col.type = column.type
        # A column reference carries the collation its column declares, wherever it
        # is written. An inner scope never changes it.
        col.collation = column.collation
        return col

    @staticmethod
    def _has(table, name: str) -> bool:
        return any(c.name.lower() == name.lower() for c in table.columns)

    @staticmethod
    def _column(table, name: str):
        for column in table.columns:
            if column.name.lower() == name.lower():
                return column
        raise BindError("TARN-201", f"table {table.name} has no column {name}")


def static_type(expr, scope) -> str:
    if isinstance(expr, A.Lit):
        value = expr.value
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        return "TEXT"
    if isinstance(expr, A.Col):
        return expr.type
    if isinstance(expr, A.Coalesce):
        seen = [t for t in (static_type(a, scope) for a in expr.args) if t != "NULL"]
        return seen[0] if seen else "NULL"
    if isinstance(expr, A.Case):
        seen = [static_type(r, scope) for _, r in expr.whens]
        seen.append(static_type(expr.otherwise, scope))
        seen = [t for t in seen if t != "NULL"]
        return seen[0] if seen else "NULL"
    if isinstance(expr, A.BinOp):
        if expr.op in ("and", "or") or expr.op in ("=", "<>", "<", "<=", ">", ">="):
            return "BOOLEAN"
        left, right = static_type(expr.left, scope), static_type(expr.right, scope)
        if "REAL" in (left, right):
            return "REAL"
        return left if left != "NULL" else right
    return (
        "BOOLEAN"
        if isinstance(expr, (A.Not, A.IsNull, A.IsNotDistinct, A.Like, A.InSubquery))
        else "NULL"
    )


def comparable(left: str, right: str) -> bool:
    if "NULL" in (left, right):
        return True
    if left in NUMERIC and right in NUMERIC:
        return True
    return left == right


def require_one_kind(kinds: list, what: str) -> None:
    present = {"numeric" if k in NUMERIC else k for k in kinds if k != "NULL"}
    if len(present) > 1:
        raise BindError("TARN-203", f"{what} mix kinds {sorted(present)}")


def bind_expr(expr, scope):
    if isinstance(expr, A.Col):
        return scope.resolve(expr)
    if isinstance(expr, A.Lit):
        return expr
    if isinstance(expr, A.BinOp):
        bind_expr(expr.left, scope)
        bind_expr(expr.right, scope)
        if expr.op in ("=", "<>", "<", "<=", ">", ">="):
            lt, rt = static_type(expr.left, scope), static_type(expr.right, scope)
            if not comparable(lt, rt):
                raise BindError("TARN-203", f"cannot compare {lt} with {rt}")
        elif expr.op in ("+", "-", "*", "/"):
            for kind in (static_type(expr.left, scope), static_type(expr.right, scope)):
                if kind not in NUMERIC and kind != "NULL":
                    raise BindError("TARN-203", f"arithmetic on {kind}")
        return expr
    if isinstance(expr, (A.Not, A.IsNull)):
        bind_expr(expr.operand, scope)
        return expr
    if isinstance(expr, A.IsNotDistinct):
        bind_expr(expr.left, scope)
        bind_expr(expr.right, scope)
        lt, rt = static_type(expr.left, scope), static_type(expr.right, scope)
        if not comparable(lt, rt):
            raise BindError("TARN-203", f"cannot compare {lt} with {rt}")
        return expr
    if isinstance(expr, A.Like):
        bind_expr(expr.operand, scope)
        bind_expr(expr.pattern, scope)
        if static_type(expr.operand, scope) not in ("TEXT", "NULL"):
            raise BindError("TARN-203", "LIKE needs a TEXT left operand")
        if static_type(expr.pattern, scope) not in ("TEXT", "NULL"):
            raise BindError("TARN-203", "LIKE needs a TEXT pattern")
        return expr
    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            bind_expr(arg, scope)
        require_one_kind([static_type(a, scope) for a in expr.args], "COALESCE arguments")
        return expr
    if isinstance(expr, A.Case):
        for cond, result in expr.whens:
            bind_expr(cond, scope)
            bind_expr(result, scope)
        bind_expr(expr.otherwise, scope)
        require_one_kind([static_type(r, scope) for _, r in expr.whens]
                         + [static_type(expr.otherwise, scope)], "CASE results")
        return expr
    if isinstance(expr, A.InSubquery):
        bind_expr(expr.operand, scope)
        expr.select = bind(expr.select, scope.catalog)
        selected = expr.select.items[0][0]
        lt = static_type(expr.operand, scope)
        rt = static_type(selected, scope)
        if not comparable(lt, rt):
            raise BindError("TARN-203", f"cannot compare {lt} with {rt}")
        return expr
    raise BindError("TARN-203", f"cannot bind {expr!r}")


def bind(select, catalog):
    scope = Scope(catalog)
    scope.add(select.source)
    for join in select.joins:
        scope.add(join.table, null_supplying=(join.kind == "left"))
    for join in select.joins:
        bind_expr(join.on, scope)
    if select.where is not None:
        bind_expr(select.where, scope)
    expanded = []
    for expr, alias in select.items:
        if expr == "*":
            for al in scope.order:
                for column in scope.aliases[al].columns:
                    ref = A.Col(qualifier=al, name=column.name)
                    scope.resolve(ref)
                    expanded.append((ref, f"{al}.{column.name}"))
            continue
        bind_expr(expr, scope)
        if alias is None:
            alias = f"{expr.alias}.{expr.name}" if isinstance(expr, A.Col) else "expr"
        expanded.append((expr, alias))
    select.items = expanded
    for item in select.order_by:
        bind_expr(item.expr, scope)
    select.scope = scope
    return select
