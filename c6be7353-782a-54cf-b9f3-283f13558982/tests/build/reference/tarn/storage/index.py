"""Sorted single-column indexes.

An index stores every row id of its table ordered by the index column, using the
collation the column declares.
"""
from .. import types as T


def _index_key(value, collation: str):
    if value is None:
        return (0,)
    if isinstance(value, str):
        return (1, T.collate_key(value, collation))
    if isinstance(value, bool):
        return (1, int(value))
    return (1, value)


class SortedIndex:
    """A list of (key, rowid) pairs held in index order."""
    def __init__(self, table, column_name: str) -> None:
        self.table = table
        self.column = table.column(column_name)
        self.entries = []
        self.rebuild()

    def rebuild(self) -> None:
        pairs = []
        for rowid, row in enumerate(self.table.rows):
            pairs.append((row.get(self.column.name), rowid))
        pairs.sort(key=lambda pair: _index_key(pair[0], self.column.collation))
        self.entries = pairs

    def ordered_rowids(self) -> list:
        return [rowid for _, rowid in self.entries]

    def ordered_rows(self) -> list:
        return [self.table.rows[rowid] for rowid in self.ordered_rowids()]
