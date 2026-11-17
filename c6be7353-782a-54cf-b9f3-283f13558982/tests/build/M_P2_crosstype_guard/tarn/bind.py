"""Name resolution and static type checks.

Binding attaches to every column reference its alias, declared type and collation,
"""
from . import ast_nodes as A
from . import types as T


class Scope:
    def __init__(self, catalog, nested: bool = False) -> None:
        self.catalog = catalog
        self.nested = nested
        self.aliases: dict = {}  # alias -> Table
        self.order: list = []  # alias order
        self.null_supplying: set = set()

    def add(self, ref: A.TableRef, null_supplying: bool = False) -> None:
        table = self.catalog.table(ref.table)
        if ref.alias in self.aliases:
            raise T.AmbiguousColumn(f"duplicate alias {ref.alias}")
        self.aliases[ref.alias] = table
        self.order.append(ref.alias)
        if null_supplying:
            self.null_supplying.add(ref.alias)

    def resolve(self, col: A.Col) -> A.Col:
        if col.qualifier is not None:
            table = self.aliases.get(col.qualifier)
            if table is None:
                raise T.UnknownTable(f"no such table alias {col.qualifier}")
            column = table.column(col.name)
            col.alias = col.qualifier
        else:
            hits = [
                (alias, tbl)
                for alias, tbl in self.aliases.items()
                if tbl.has_column(col.name)
            ]
            if not hits:
                raise T.UnknownColumn(f"no such column {col.name}")
            if len(hits) > 1:
                raise T.AmbiguousColumn(f"column {col.name} is ambiguous")
            col.alias, table = hits[0]
            column = table.column(col.name)
        col.name = column.name
        col.type = column.type
        col.collation = T.BINARY if self.nested else column.collation
        return col

    def declared_nullable(self, alias: str, name: str) -> bool:
        if alias in self.null_supplying:
            return True
        return self.aliases[alias].column(name).nullable

    def columns_of(self, alias: str) -> set:
        return {f"{alias}.{c.name}" for c in self.aliases[alias].columns}


def _static_type(expr, scope):
    if isinstance(expr, A.Lit):
        return T.kind(expr.value)
    if isinstance(expr, A.Col):
        return expr.type
    if isinstance(expr, A.Coalesce):
        seen = [t for t in (_static_type(a, scope) for a in expr.args) if t != T.NULL]
        return seen[0] if seen else T.NULL
    if isinstance(expr, A.Case):
        seen = [_static_type(r, scope) for _, r in expr.whens]
        seen.append(_static_type(expr.otherwise, scope))
        seen = [t for t in seen if t != T.NULL]
        return seen[0] if seen else T.NULL
    if isinstance(expr, A.BinOp):
        if expr.op in ("and", "or") or expr.op in ("=", "<>", "<", "<=", ">", ">="):
            return T.BOOLEAN
        left = _static_type(expr.left, scope)
        right = _static_type(expr.right, scope)
        if T.REAL in (left, right):
            return T.REAL
        return left if left != T.NULL else right
    if isinstance(expr, (A.Not, A.IsNull, A.IsNotDistinct, A.Like, A.InSubquery)):
        return T.BOOLEAN
    return T.NULL


def _comparable(left: str, right: str) -> bool:
    if T.NULL in (left, right):
        return True
    if left in T.NUMERIC_TYPES and right in T.NUMERIC_TYPES:
        return True
    return left == right


def _one_kind(kinds: list, what: str) -> None:
    classes = {"numeric" if k in T.NUMERIC_TYPES else k for k in kinds if k != T.NULL}
    if len(classes) > 1:
        raise T.TypeMismatch(f"{what} mix kinds {', '.join(sorted(classes))}")


def bind_expr(expr, scope):
    if isinstance(expr, A.Col):
        return scope.resolve(expr)
    if isinstance(expr, A.Lit):
        return expr
    if isinstance(expr, A.BinOp):
        bind_expr(expr.left, scope)
        bind_expr(expr.right, scope)
        if expr.op in ("=", "<>", "<", "<=", ">", ">="):
            lt = _static_type(expr.left, scope)
            rt = _static_type(expr.right, scope)
            if not _comparable(lt, rt):
                raise T.TypeMismatch(f"cannot compare {lt} with {rt}")
        if expr.op in ("+", "-", "*", "/"):
            for side in (expr.left, expr.right):
                kind = _static_type(side, scope)
                if kind != T.NULL and kind not in T.NUMERIC_TYPES:
                    raise T.TypeMismatch(f"arithmetic needs numeric operands, not {kind}")
        return expr
    if isinstance(expr, A.Not):
        bind_expr(expr.operand, scope)
        return expr
    if isinstance(expr, A.IsNull):
        bind_expr(expr.operand, scope)
        return expr
    if isinstance(expr, A.IsNotDistinct):
        bind_expr(expr.left, scope)
        bind_expr(expr.right, scope)
        lt = _static_type(expr.left, scope)
        rt = _static_type(expr.right, scope)
        if not _comparable(lt, rt):
            raise T.TypeMismatch(f"cannot compare {lt} with {rt}")
        return expr
    if isinstance(expr, A.Like):
        bind_expr(expr.operand, scope)
        bind_expr(expr.pattern, scope)
        if _static_type(expr.operand, scope) not in (T.TEXT, T.NULL):
            raise T.TypeMismatch("LIKE needs a TEXT left operand")
        if _static_type(expr.pattern, scope) not in (T.TEXT, T.NULL):
            raise T.TypeMismatch("LIKE needs a TEXT pattern")
        return expr
    if isinstance(expr, A.Coalesce):
        for arg in expr.args:
            bind_expr(arg, scope)
        _one_kind([_static_type(a, scope) for a in expr.args], "COALESCE arguments")
        return expr
    if isinstance(expr, A.Case):
        for cond, result in expr.whens:
            bind_expr(cond, scope)
            bind_expr(result, scope)
        bind_expr(expr.otherwise, scope)
        _one_kind([_static_type(r, scope) for _, r in expr.whens]
                  + [_static_type(expr.otherwise, scope)], "CASE results")
        return expr
    if isinstance(expr, A.InSubquery):
        bind_expr(expr.operand, scope)
        expr.select = bind(expr.select, scope.catalog, nested=True)
        lt = _static_type(expr.operand, scope)
        rt = _static_type(expr.select.items[0][0], expr.select.scope)
        if not _comparable(lt, rt):
            raise T.TypeMismatch(f"cannot compare {lt} with {rt}")
        return expr
    raise T.TypeMismatch(f"cannot bind {expr!r}")


def bind(select: A.Select, catalog, nested: bool = False) -> A.Select:
    scope = Scope(catalog, nested=nested)
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
                for col in scope.aliases[al].columns:
                    ref = A.Col(qualifier=al, name=col.name)
                    scope.resolve(ref)
                    expanded.append((ref, f"{al}.{col.name}"))
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
