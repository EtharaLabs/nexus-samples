"""The reference investigation: the calls a solver makes, and the findings they prove.

Each defect gets a series of probes on a shared probe database that isolates it, then
a minimal finding built for it on a database of its own: no row, column, table,
index, select item, conjunct, join, ORDER BY key or LIMIT can be taken away from it
while the defect still shows. The finding is run once to reproduce it and once more
with one element taken away, which shows where the defect stops. plan() lists every
call in order, which is what solve.sh replays and what the budget has to cover.
"""

import copy
import json
import pathlib

DB_MAIN = "probe_main.json"
DB_DEEP = "probe_deep.json"
VERB = {"plan": "explain", "answer": "execute", "error": "execute"}


def col(name, kind, collation=None, nullable=True):
    out = {"name": name, "type": kind, "nullable": nullable}
    if collation:
        out["collation"] = collation
    return out


def db(tables, indexes=None):
    return {"tables": {name: {"columns": cols, "rows": rows}
                       for name, (cols, rows) in tables.items()},
            "indexes": indexes or []}


PROBES = {
    "P1": {
        "section": "6.3",
        "kind": "plan",
        "probe_database": DB_DEEP,
        "finding": {
            "database": db({"a": ([col("id", "INTEGER")], []),
                            "b": ([col("id", "INTEGER"), col("a", "INTEGER"), col("v", "INTEGER")], []),
                            "c": ([col("b", "INTEGER")], [])}),
            "sql": "SELECT a.id FROM a a LEFT JOIN b b ON a.id = b.a "
                   "LEFT JOIN c c ON c.b = b.id WHERE b.v = 5",
        },
        "boundary": ("join 1", None, "SELECT a.id FROM a a LEFT JOIN b b ON a.id = b.a WHERE b.v = 5"),
        "calls": [
            ("explain", "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
                        "WHERE t.s = 'open' ORDER BY a.id"),
            ("explain", "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
                        "LEFT JOIN w w ON w.code = t.s WHERE t.s = 'open' ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
                        "LEFT JOIN w w ON w.code = t.s WHERE t.s = 'open' ORDER BY a.id"),
            ("explain", "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
                        "LEFT JOIN w w ON w.code = t.s WHERE t.amt > 5 ORDER BY a.id"),
        ],
    },
    "P2": {
        "section": "8",
        "kind": "plan",
        "probe_database": DB_MAIN,
        "finding": {
            "database": db({"a": ([col("k", "INTEGER")], []),
                            "b": ([col("k", "REAL")], [[float(i)] for i in range(1, 9)])}),
            "sql": "SELECT a.k FROM a a JOIN b b ON a.k = b.k",
        },
        "boundary": ("row 7 of b", ("b", 7), None),
        "calls": [
            ("explain", "SELECT a.id, u.v FROM a a JOIN u u ON u.k = a.k ORDER BY a.id"),
            ("explain", "SELECT a.id, u.v FROM a a JOIN u u ON u.k = a.r ORDER BY a.id, u.v"),
            ("execute", "SELECT a.id, u.v FROM a a JOIN u u ON u.k = a.r ORDER BY a.id, u.v"),
        ],
    },
    "P3": {
        "section": "5",
        "kind": "answer",
        "probe_database": DB_MAIN,
        "finding": {
            "database": db({"o": ([col("id", "INTEGER")], [[1]]),
                            "n": ([col("k", "TEXT", "NOCASE")], [["A"]])}),
            "sql": "SELECT o.id FROM o o WHERE 'a' IN (SELECT n.k FROM n n)",
        },
        "boundary": ("WHERE", None, "SELECT o.id FROM o o"),
        "calls": [
            ("execute", "SELECT u.v FROM u u WHERE u.v = 'abc' ORDER BY u.v"),
            ("execute", "SELECT a.id FROM a a WHERE a.b IN (SELECT u.v FROM u u) ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a WHERE a.b IN (SELECT u.v FROM u u "
                        "WHERE u.v = 'abc') ORDER BY a.id"),
        ],
    },
    "P4": {
        "section": "2",
        "kind": "error",
        "probe_database": DB_MAIN,
        "finding": {
            "database": db({"a": ([col("id", "INTEGER")], [[1]]),
                            "e": ([col("y", "INTEGER")], [[1]])}),
            "sql": "SELECT a.id FROM a a JOIN e e ON a.id IN (SELECT x.y FROM e x)",
        },
        "boundary": ("join 0", None, "SELECT a.id FROM a a"),
        "calls": [
            ("execute", "SELECT a.id FROM a a WHERE a.k IN (SELECT u.k FROM u u) ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a JOIN t t ON t.aid IN (SELECT u.k FROM u u) "
                        "ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a JOIN t t ON t.aid = a.id ORDER BY a.id"),
        ],
    },
    "P5": {
        "section": "7",
        "kind": "answer",
        "probe_database": DB_MAIN,
        "finding": {
            "database": db({"t": ([col("id", "INTEGER"), col("n", "TEXT", "NOCASE")],
                                  [[1, "A"], [2, "_"]])},
                           [{"name": "t_n", "table": "t", "column": "n"}]),
            "sql": "SELECT t.id FROM t t ORDER BY t.n",
        },
        "boundary": ("index t_n", ("index", 0), None),
        "calls": [
            ("execute", "SELECT a.id FROM a a ORDER BY a.k"),
            ("execute", "SELECT a.id FROM a a ORDER BY a.n"),
            ("execute", "SELECT a.id FROM a a ORDER BY a.b"),
            ("explain", "SELECT a.id FROM a a ORDER BY a.n"),
        ],
    },
    "P6": {
        "section": "6.3",
        "kind": "answer",
        "probe_database": DB_DEEP,
        "finding": {
            "database": db({"a": ([col("id", "INTEGER")], [[1]]),
                            "b": ([col("id", "INTEGER"), col("a", "INTEGER")], [[1, 1]]),
                            "c": ([col("b", "INTEGER"), col("u", "INTEGER")], [[1, 10]])}),
            "sql": "SELECT a.id FROM a a LEFT JOIN b b ON a.id = b.a "
                   "LEFT JOIN c c ON c.b = b.id WHERE c.u IS NULL",
        },
        "boundary": ("row 0 of c", ("c", 0), None),
        "calls": [
            ("execute", "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
                        "WHERE COALESCE(t.s, 'zzz') = 'zzz' ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a JOIN w w ON w.code = 'open' "
                        "LEFT JOIN t t ON t.aid = a.id "
                        "WHERE COALESCE(t.s, 'zzz') = 'zzz' ORDER BY a.id"),
            ("explain", "SELECT a.id FROM a a JOIN w w ON w.code = 'open' "
                        "LEFT JOIN t t ON t.aid = a.id "
                        "WHERE COALESCE(t.s, 'zzz') = 'zzz' ORDER BY a.id"),
        ],
    },
    "P7": {
        "section": "5",
        "kind": "answer",
        "probe_database": DB_MAIN,
        "finding": {
            "database": db({"t": ([col("id", "INTEGER"), col("n", "TEXT", "NOCASE")], [[1, "A"]])}),
            "sql": "SELECT t.id FROM t t WHERE COALESCE(t.n, 'x') = 'a'",
        },
        "boundary": ("WHERE", None, "SELECT t.id FROM t t"),
        "calls": [
            ("execute", "SELECT a.id FROM a a WHERE a.n = 'ABC' ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a WHERE COALESCE(a.n, 'x') = 'ABC' ORDER BY a.id"),
            ("execute", "SELECT a.id FROM a a WHERE COALESCE(a.n, 'x') LIKE 'ab%' ORDER BY a.id"),
        ],
    },
}

ORIENTATION = [
    ("execute", "SELECT a.id, a.n, a.b, a.r, a.k FROM a a ORDER BY a.id"),
    ("execute", "SELECT t.id, t.aid, t.s, t.amt FROM t t ORDER BY t.id"),
    ("execute", "SELECT u.k, u.v FROM u u ORDER BY u.k, u.v"),
    ("execute", "SELECT w.code, w.label FROM w w ORDER BY w.code"),
    ("explain", "SELECT a.id FROM a a ORDER BY a.id"),
]


def probe_databases() -> dict:
    here = pathlib.Path(__file__).parent
    return {name: json.loads((here / name).read_text(encoding="utf-8"))
            for name in (DB_MAIN, DB_DEEP)}


def boundary(probe: dict) -> tuple:
    """The finding's database and statement with the one element `boundary` names
    taken away: a row (table, index), an index ("index", position), or a statement."""
    label, cut, sql = probe["boundary"]
    database = copy.deepcopy(probe["finding"]["database"])
    if cut is not None and cut[0] == "index":
        del database["indexes"][cut[1]]
    elif cut is not None:
        del database["tables"][cut[0]]["rows"][cut[1]]
    return label, database, sql or probe["finding"]["sql"]


def findings() -> list:
    return [{"section": p["section"], "kind": p["kind"],
             "database": p["finding"]["database"], "sql": p["finding"]["sql"]}
            for p in PROBES.values()]


def plan() -> list:
    """Every call of the investigation in order, as (verb, database, sql)."""
    dbs = probe_databases()
    calls = [(verb, dbs[DB_MAIN], sql) for verb, sql in ORIENTATION]
    for probe in PROBES.values():
        calls += [(verb, dbs[probe["probe_database"]], sql) for verb, sql in probe["calls"]]
        verb = VERB[probe["kind"]]
        calls.append((verb, probe["finding"]["database"], probe["finding"]["sql"]))
        _, database, sql = boundary(probe)
        calls.append((verb, database, sql))
    return calls


if __name__ == "__main__":
    out = pathlib.Path(__file__).parent / "findings.json"
    out.write_text(json.dumps(findings(), indent=2) + "\n", encoding="utf-8")
    calls = plan()
    print(f"reference findings: {len(findings())} entries -> {out.name}")
    print(f"reference call count: {len(calls)} ({len(ORIENTATION)} orientation, "
          f"{sum(len(p['calls']) for p in PROBES.values())} probes, "
          f"{2 * len(PROBES)} reproduction and boundary)")
