"""Schema objects and the JSON database loader."""
from dataclasses import dataclass, field

from . import types as T


@dataclass
class Column:
    name: str
    type: str
    collation: str = T.BINARY
    nullable: bool = True


@dataclass
class Index:
    name: str
    table: str
    column: str


@dataclass
class Table:
    name: str
    columns: list
    rows: list = field(default_factory=list)

    def column(self, name: str) -> Column:
        low = name.lower()
        for col in self.columns:
            if col.name.lower() == low:
                return col
        raise T.UnknownColumn(f"table {self.name} has no column {name}")

    def has_column(self, name: str) -> bool:
        low = name.lower()
        return any(c.name.lower() == low for c in self.columns)

    @property
    def column_names(self) -> list:
        return [c.name for c in self.columns]


class Catalog:
    def __init__(self) -> None:
        self.tables: dict = {}
        self.indexes: list = []

    def add_table(self, table: Table) -> None:
        self.tables[table.name.lower()] = table

    def table(self, name: str) -> Table:
        try:
            return self.tables[name.lower()]
        except KeyError:
            raise T.UnknownTable(f"no such table {name}") from None

    def add_index(self, index: Index) -> None:
        self.indexes.append(index)

    def index_for(self, table: str, column: str):
        for idx in self.indexes:
            if (
                idx.table.lower() == table.lower()
                and idx.column.lower() == column.lower()
            ):
                return idx
        return None

    @classmethod
    def from_dict(cls, payload: dict) -> "Catalog":
        cat = cls()
        for tname, tdef in payload.get("tables", {}).items():
            cols = [
                Column(
                    name=c["name"],
                    type=c["type"],
                    collation=c.get("collation", T.BINARY),
                    nullable=c.get("nullable", True),
                )
                for c in tdef["columns"]
            ]
            rows = []
            for raw in tdef.get("rows", []):
                row = {}
                for col, value in zip(cols, raw):
                    row[col.name] = value
                rows.append(row)
            cat.add_table(Table(name=tname, columns=cols, rows=rows))
        for idef in payload.get("indexes", []):
            cat.add_index(
                Index(name=idef["name"], table=idef["table"], column=idef["column"])
            )
        return cat
