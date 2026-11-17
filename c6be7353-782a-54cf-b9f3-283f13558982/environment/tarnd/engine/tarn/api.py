"""The public engine API: connect, execute, explain, stats."""
import json
from dataclasses import dataclass, field

from . import bind as B
from . import parse as P
from .catalog import Catalog
from .exec import operators as O
from .plan import explain as X
from .plan import pipeline as PL


@dataclass
class Result:
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


class Connection:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.stats = O.Stats()
        self.disabled_rules = frozenset()

    def _runner(self):
        def run(sub):
            return self._run_subquery(sub)

        return run

    def _run_subquery(self, sub) -> list:
        ctx = PL.Ctx(self.catalog, sub.scope)
        logical = PL.optimize(PL.build_logical(sub), ctx, self.disabled_rules)
        op = PL.build_physical(logical, ctx, self.stats, self._runner())
        return [row[0] for row in op.rows()]

    def _plan(self, sql: str):
        select = B.bind(P.parse(sql), self.catalog)
        ctx = PL.Ctx(self.catalog, select.scope)
        logical = PL.optimize(PL.build_logical(select), ctx, self.disabled_rules)
        return PL.build_physical(logical, ctx, self.stats, self._runner())

    def execute(self, sql: str) -> Result:
        self.stats.reset()
        op = self._plan(sql)
        rows = op.rows()
        columns = op.column_names if isinstance(op, O.Project) else []
        return Result(columns=columns, rows=rows)

    def explain(self, sql: str) -> str:
        self.stats.reset()
        return X.render(self._plan(sql))


def connect(database) -> Connection:
    if isinstance(database, Catalog):
        return Connection(database)
    if isinstance(database, dict):
        return Connection(Catalog.from_dict(database))
    with open(database, encoding="utf-8") as handle:
        return Connection(Catalog.from_dict(json.load(handle)))
