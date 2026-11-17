"""Physical operators.

Every operator materializes its output and adds the rows it examined to the shared
`stats` counter, which conn.stats.rows_processed reports.
"""
from .. import types as T
from . import expr as E
from .hashing import join_key


class Stats:
    def __init__(self) -> None:
        self.rows_processed = 0

    def reset(self) -> None:
        self.rows_processed = 0


class Op:
    name = "Op"

    def __init__(self, stats: Stats) -> None:
        self.stats = stats
        self.subquery = None
        self.collation = None

    def rows(self) -> list:
        raise NotImplementedError

    def children(self) -> list:
        return []

    def label(self) -> str:
        return self.name


class SeqScan(Op):
    name = "SeqScan"

    def __init__(self, table, alias: str, stats: Stats) -> None:
        super().__init__(stats)
        self.table = table
        self.alias = alias

    def rows(self) -> list:
        out = []
        for row in self.table.rows:
            out.append({f"{self.alias}.{k}": v for k, v in row.items()})
        self.stats.rows_processed += len(out)
        return out

    def label(self) -> str:
        return f"SeqScan {self.table.name} AS {self.alias}"


class IndexScan(Op):
    name = "IndexScan"

    def __init__(self, table, alias: str, index, stats: Stats) -> None:
        super().__init__(stats)
        self.table = table
        self.alias = alias
        self.index = index

    def rows(self) -> list:
        out = []
        for row in self.index.ordered_rows():
            out.append({f"{self.alias}.{k}": v for k, v in row.items()})
        self.stats.rows_processed += len(out)
        return out

    def label(self) -> str:
        return (
            f"IndexScan {self.table.name} AS {self.alias} ON {self.index.column.name}"
        )


def _pad(row: dict, keys: list) -> dict:
    out = dict(row)
    for key in keys:
        out[key] = None
    return out


class NestedLoopJoin(Op):
    name = "NestedLoopJoin"

    def __init__(
        self, left: Op, right: Op, on, kind: str, right_keys: list, stats: Stats
    ) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right
        self.on = on
        self.kind = kind
        self.right_keys = right_keys

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        left_rows = self.left.rows()
        right_rows = self.right.rows()
        out = []
        for lrow in left_rows:
            matched = False
            for rrow in right_rows:
                self.stats.rows_processed += 1
                combined = {**lrow, **rrow}
                if E.truthy(E.eval_expr(self.on, combined)):
                    out.append(combined)
                    matched = True
            if not matched and self.kind == "left":
                out.append(_pad(lrow, self.right_keys))
        return out

    def label(self) -> str:
        return f"NestedLoopJoin kind={self.kind}"


class HashJoin(Op):
    name = "HashJoin"

    def __init__(
        self,
        left: Op,
        right: Op,
        left_expr,
        right_expr,
        kind: str,
        right_keys: list,
        stats: Stats,
        collation: str | None = None,
    ) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right
        self.left_expr = left_expr
        self.right_expr = right_expr
        self.kind = kind
        self.right_keys = right_keys
        self.collation = collation

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        left_rows = self.left.rows()
        right_rows = self.right.rows()
        collation = self.collation or E.comparison_collation(
            self.left_expr, self.right_expr
        )
        buckets: dict = {}
        for rrow in right_rows:
            self.stats.rows_processed += 1
            key = join_key(E.eval_expr(self.right_expr, rrow, self.subquery), collation)
            if key is None:
                continue
            buckets.setdefault(key, []).append(rrow)
        out = []
        for lrow in left_rows:
            self.stats.rows_processed += 1
            key = join_key(E.eval_expr(self.left_expr, lrow, self.subquery), collation)
            hits = buckets.get(key, []) if key is not None else []
            for rrow in hits:
                out.append({**lrow, **rrow})
            if not hits and self.kind == "left":
                out.append(_pad(lrow, self.right_keys))
        return out

    def label(self) -> str:
        return f"HashJoin kind={self.kind}"


class MergeJoin(Op):
    """Joins two inputs that already arrive in join-key order."""
    name = "MergeJoin"

    def __init__(
        self,
        left: Op,
        right: Op,
        left_expr,
        right_expr,
        stats: Stats,
        collation: str | None = None,
    ) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right
        self.left_expr = left_expr
        self.right_expr = right_expr
        self.collation = collation

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        left_rows = self.left.rows()
        right_rows = self.right.rows()
        collation = self.collation or E.comparison_collation(
            self.left_expr, self.right_expr
        )
        out = []
        i = j = 0
        while i < len(left_rows) and j < len(right_rows):
            self.stats.rows_processed += 1
            lvalue = E.eval_expr(self.left_expr, left_rows[i], self.subquery)
            rvalue = E.eval_expr(self.right_expr, right_rows[j], self.subquery)
            if lvalue is None:
                i += 1
                continue
            if rvalue is None:
                j += 1
                continue
            lkey = T.order_key(lvalue, collation)
            rkey = T.order_key(rvalue, collation)
            if lkey < rkey:
                i += 1
                continue
            if lkey > rkey:
                j += 1
                continue
            iend = i
            while iend < len(left_rows):
                value = E.eval_expr(self.left_expr, left_rows[iend], self.subquery)
                if value is None or T.order_key(value, collation) != lkey:
                    break
                iend += 1
            jend = j
            while jend < len(right_rows):
                value = E.eval_expr(self.right_expr, right_rows[jend], self.subquery)
                if value is None or T.order_key(value, collation) != rkey:
                    break
                jend += 1
            for li in range(i, iend):
                for jj in range(j, jend):
                    out.append({**left_rows[li], **right_rows[jj]})
            i, j = iend, jend
        return out

    def label(self) -> str:
        return "MergeJoin kind=inner"


class AntiMatch(Op):
    """The left rows with no join partner under `on`."""
    name = "AntiMatch"

    def __init__(self, left: Op, right: Op, on, stats: Stats) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right
        self.on = on

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        left_rows = self.left.rows()
        right_rows = self.right.rows()
        out = []
        for lrow in left_rows:
            matched = False
            for rrow in right_rows:
                self.stats.rows_processed += 1
                if E.truthy(E.eval_expr(self.on, {**lrow, **rrow}, self.subquery)):
                    matched = True
                    break
            if not matched:
                out.append(lrow)
        return out


class AntiJoin(Op):
    """Emits the left rows that NOT IN keeps."""
    name = "AntiJoin"

    def __init__(
        self, left: Op, right: Op, left_expr, right_expr, null_aware: bool, stats: Stats
    ) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right
        self.left_expr = left_expr
        self.right_expr = right_expr
        self.null_aware = null_aware

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        left_rows = self.left.rows()
        right_rows = self.right.rows()
        collation = self.collation or E.comparison_collation(
            self.left_expr, self.right_expr
        )
        values = []
        saw_null = False
        for rrow in right_rows:
            self.stats.rows_processed += 1
            value = E.eval_expr(self.right_expr, rrow, self.subquery)
            if value is None:
                saw_null = True
            else:
                values.append(value)
        buckets = {join_key(v, collation) for v in values}
        out = []
        for lrow in left_rows:
            self.stats.rows_processed += 1
            if not right_rows:
                out.append(lrow)
                continue
            value = E.eval_expr(self.left_expr, lrow, self.subquery)
            if value is None:
                continue
            if join_key(value, collation) in buckets:
                continue
            if self.null_aware and saw_null:
                continue
            out.append(lrow)
        return out

    def label(self) -> str:
        return "NullAwareAntiJoin" if self.null_aware else "AntiJoin"


class NullPad(Op):
    name = "NullPad"

    def __init__(self, child: Op, pad_keys: list, stats: Stats) -> None:
        super().__init__(stats)
        self.child = child
        self.pad_keys = pad_keys

    def children(self) -> list:
        return [self.child]

    def rows(self) -> list:
        return [_pad(row, self.pad_keys) for row in self.child.rows()]


class Filter(Op):
    name = "Filter"

    def __init__(self, child: Op, pred, stats: Stats, subquery=None) -> None:
        super().__init__(stats)
        self.child = child
        self.pred = pred
        self.subquery = subquery

    def children(self) -> list:
        return [self.child]

    def rows(self) -> list:
        out = []
        for row in self.child.rows():
            self.stats.rows_processed += 1
            if E.truthy(E.eval_expr(self.pred, row, self.subquery)):
                out.append(row)
        return out


class UnionAll(Op):
    name = "UnionAll"

    def __init__(self, left: Op, right: Op, stats: Stats) -> None:
        super().__init__(stats)
        self.left = left
        self.right = right

    def children(self) -> list:
        return [self.left, self.right]

    def rows(self) -> list:
        return self.left.rows() + self.right.rows()


class Sort(Op):
    name = "Sort"

    def __init__(self, child: Op, keys: list, stats: Stats) -> None:
        super().__init__(stats)
        self.child = child
        self.keys = keys

    def children(self) -> list:
        return [self.child]

    def rows(self) -> list:
        rows = self.child.rows()
        self.stats.rows_processed += len(rows)
        for item in reversed(self.keys):
            collation = E._collation_of(item.expr)
            rows.sort(
                key=lambda row, it=item, coll=collation: T.order_key(
                    E.eval_expr(it.expr, row, self.subquery), coll
                ),
                reverse=(item.direction == "desc"),
            )
        return rows


class Limit(Op):
    name = "Limit"

    def __init__(self, child: Op, count: int, stats: Stats) -> None:
        super().__init__(stats)
        self.child = child
        self.count = count

    def children(self) -> list:
        return [self.child]

    def rows(self) -> list:
        return self.child.rows()[: self.count]


class Project(Op):
    name = "Project"

    def __init__(self, child: Op, items: list, stats: Stats, subquery=None) -> None:
        super().__init__(stats)
        self.child = child
        self.items = items
        self.subquery = subquery

    def children(self) -> list:
        return [self.child]

    @property
    def column_names(self) -> list:
        return [alias for _, alias in self.items]

    def rows(self) -> list:
        out = []
        for row in self.child.rows():
            out.append([E.eval_expr(e, row, self.subquery) for e, _ in self.items])
        return out
