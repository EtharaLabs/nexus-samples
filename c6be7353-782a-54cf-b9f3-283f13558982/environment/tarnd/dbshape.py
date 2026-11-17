"""What a valid database is, and how the service names one in its call log.

The query service refuses a database this module rejects, and the grader applies the
same rule to every finding, so a database the engine was never asked about can never
be graded. The digest is the one the service writes into calls.jsonl.
"""

import hashlib
import json
import math
import re

KINDS = ("INTEGER", "REAL", "TEXT", "BOOLEAN")
COLLATIONS = ("BINARY", "NOCASE")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def digest(database) -> str:
    raw = json.dumps(database, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _fits(kind: str, value) -> bool:
    if kind == "BOOLEAN":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if kind == "INTEGER":
        return isinstance(value, int)
    if kind == "REAL":
        return isinstance(value, (int, float)) and math.isfinite(value)
    return isinstance(value, str)


def problem(database) -> str | None:
    """Why ``database`` is not a valid database, or None when it is."""
    if not isinstance(database, dict):
        return "a database is a JSON object"
    tables = database.get("tables")
    if not isinstance(tables, dict) or not tables:
        return 'a database needs a non-empty "tables" object'
    seen_tables = set()
    for tname, tdef in tables.items():
        if not isinstance(tname, str) or not IDENT.match(tname):
            return f"table name {tname!r} is not an identifier"
        if tname.lower() in seen_tables:
            return f"table {tname} is declared twice"
        seen_tables.add(tname.lower())
        if not isinstance(tdef, dict):
            return f"table {tname} is not an object"
        columns = tdef.get("columns")
        if not isinstance(columns, list) or not columns:
            return f'table {tname} needs a non-empty "columns" list'
        names = set()
        for col in columns:
            if not isinstance(col, dict):
                return f"a column of {tname} is not an object"
            cname = col.get("name")
            if not isinstance(cname, str) or not IDENT.match(cname):
                return f"a column of {tname} has no identifier name"
            if cname.lower() in names:
                return f"column {cname} of {tname} is declared twice"
            names.add(cname.lower())
            if col.get("type") not in KINDS:
                return (
                    f"column {tname}.{cname} declares no kind among {', '.join(KINDS)}"
                )
            if "collation" in col:
                if col["type"] != "TEXT":
                    return (
                        f"column {tname}.{cname} declares a collation but is not TEXT"
                    )
                if col["collation"] not in COLLATIONS:
                    return f"column {tname}.{cname} declares no collation among BINARY, NOCASE"
            if "nullable" in col and not isinstance(col["nullable"], bool):
                return (
                    f'column {tname}.{cname} has a "nullable" that is not true or false'
                )
        rows = tdef.get("rows", [])
        if not isinstance(rows, list):
            return f'table {tname} has a "rows" that is not a list'
        for r, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(columns):
                return f"row {r} of {tname} does not hold one value per column"
            for col, value in zip(columns, row):
                if value is None:
                    if col.get("nullable", True) is False:
                        return f"row {r} of {tname} holds NULL in NOT NULL column {col['name']}"
                elif not _fits(col["type"], value):
                    return f"row {r} of {tname} holds {value!r}, which is not of kind {col['type']}"
    indexes = database.get("indexes", [])
    if not isinstance(indexes, list):
        return '"indexes" is not a list'
    index_names = set()
    for idx in indexes:
        if not isinstance(idx, dict):
            return "an index is not an object"
        iname = idx.get("name")
        if not isinstance(iname, str) or not IDENT.match(iname):
            return "an index has no identifier name"
        if iname.lower() in index_names:
            return f"index {iname} is declared twice"
        index_names.add(iname.lower())
        table = next(
            (
                t
                for t in tables
                if isinstance(idx.get("table"), str)
                and t.lower() == idx["table"].lower()
            ),
            None,
        )
        if table is None:
            return f"index {iname} names no table of the database"
        column = idx.get("column")
        if not isinstance(column, str) or column.lower() not in {
            c["name"].lower() for c in tables[table]["columns"]
        }:
            return f"index {iname} names no column of {table}"
    return None
