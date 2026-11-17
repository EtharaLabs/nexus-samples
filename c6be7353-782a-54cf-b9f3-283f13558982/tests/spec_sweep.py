"""The spec sweep: what a careful reader finds without insight.

For each numbered rule in DESIGN.md this runs the one to three simplest queries such
a reader would write to test it, over a small database built for the purpose, and
compares the shipped engine with the reference on answers, plans and rows processed.
A defect the sweep catches is a defect the agent finds the same way, so the target is
that it catches at most three of the seven.

    python3 spec_sweep.py            report the catch list
    python3 spec_sweep.py --verbose  also list every query that differed
"""

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "tests" / "build"

DB = {
    "tables": {
        "a": {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False},
                {"name": "n", "type": "TEXT", "collation": "NOCASE", "nullable": True},
                {"name": "b", "type": "TEXT", "collation": "BINARY", "nullable": True},
                {"name": "r", "type": "REAL", "nullable": True},
                {"name": "k", "type": "INTEGER", "nullable": True},
            ],
            "rows": [
                [1, "abc", "abc", 1.0, 10],
                [2, "ABC", "ABC", 2.0, None],
                [3, "zed", "zed", 3.0, 20],
                [4, None, None, None, 10],
                [5, "Zed", "Zed", 5.0, 30],
            ],
        },
        "t": {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False},
                {"name": "aid", "type": "INTEGER", "nullable": True},
                {"name": "s", "type": "TEXT", "nullable": True},
                {"name": "amt", "type": "INTEGER", "nullable": True},
            ],
            "rows": [
                [100, 1, "open", 5],
                [101, 1, "shut", 7],
                [102, 2, "shut", 9],
                [103, None, "open", 11],
            ],
        },
        "u": {
            "columns": [
                {"name": "k", "type": "INTEGER", "nullable": True},
                {"name": "v", "type": "TEXT", "collation": "NOCASE", "nullable": True},
            ],
            "rows": [
                [10, "abc"],
                [20, "ZED"],
                [None, "qq"],
                [30, "zz"],
                [10, "ABC"],
                [20, "zed"],
                [40, "mm"],
                [50, "nn"],
                [60, "oo"],
            ],
        },
        "w": {
            "columns": [
                {"name": "code", "type": "TEXT", "nullable": False},
                {"name": "label", "type": "TEXT", "nullable": False},
            ],
            "rows": [["open", "Open"], ["shut", "Shut"]],
        },
    },
    "indexes": [
        {"name": "a_k", "table": "a", "column": "k"},
        {"name": "a_n", "table": "a", "column": "n"},
        {"name": "u_k", "table": "u", "column": "k"},
    ],
}

# One entry per numbered rule, with the simplest queries that test it.
SWEEP = {
    "3 kinds and exact numeric comparison": [
        "SELECT a.id FROM a a WHERE a.k = 10 ORDER BY a.id",
        "SELECT a.id FROM a a WHERE a.r = 1 ORDER BY a.id",
        "SELECT -7 / 2 AS q FROM w w ORDER BY w.code LIMIT 1",
    ],
    "4 three-valued logic": [
        "SELECT a.id FROM a a WHERE a.k = 10 OR a.n IS NULL ORDER BY a.id",
        "SELECT a.id FROM a a WHERE NOT (a.k = 10) ORDER BY a.id",
        "SELECT a.id, COALESCE(a.n, 'none') AS c FROM a a ORDER BY a.id",
    ],
    "4.1 IN and NOT IN": [
        "SELECT a.id FROM a a WHERE a.k NOT IN (SELECT u.k FROM u u) ORDER BY a.id",
        "SELECT a.id FROM a a WHERE a.k NOT IN (SELECT u.k FROM u u WHERE u.k > 9999) "
        "ORDER BY a.id",
        "SELECT a.id FROM a a WHERE a.k IN (SELECT u.k FROM u u) ORDER BY a.id",
    ],
    "5 collation and LIKE": [
        "SELECT a.id FROM a a WHERE a.n = 'ABC' ORDER BY a.id",
        "SELECT a.id FROM a a WHERE a.n LIKE 'ab%' ORDER BY a.id",
        "SELECT a.id FROM a a WHERE a.b LIKE 'ab%' ORDER BY a.id",
    ],
    "5 collation through COALESCE and CASE": [
        "SELECT a.id FROM a a WHERE COALESCE(a.n, 'x') = 'ABC' ORDER BY a.id",
    ],
    "5 collation in a subquery": [
        "SELECT a.id FROM a a WHERE a.b IN (SELECT u.v FROM u u) ORDER BY a.id",
    ],
    "6.2 fold": [
        "SELECT a.id FROM a a WHERE 1 = 1 AND a.id > 2 ORDER BY a.id",
    ],
    "6.3 outer join simplification": [
        "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id WHERE t.s = 'open' ORDER BY a.id",
        "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id "
        "WHERE COALESCE(t.s, 'none') = 'none' ORDER BY a.id",
        "SELECT a.id FROM a a LEFT JOIN t t ON t.aid = a.id WHERE t.id IS NULL ORDER BY a.id",
    ],
    "6.4 NOT IN rewriting": [
        "SELECT a.id FROM a a WHERE a.id NOT IN (SELECT t.aid FROM t t) ORDER BY a.id",
    ],
    "6.5 pushdown": [
        "SELECT a.id FROM a a JOIN t t ON t.aid = a.id WHERE a.id > 1 AND t.amt > 5 "
        "ORDER BY a.id",
    ],
    "6.6 sort elimination": [
        "SELECT a.id FROM a a ORDER BY a.k",
        "SELECT a.id FROM a a ORDER BY a.n",
    ],
    "7 ordering": [
        "SELECT a.id FROM a a ORDER BY a.k DESC",
        "SELECT a.id FROM a a ORDER BY a.b",
    ],
    "8 physical join choice": [
        "SELECT a.id, u.v FROM a a JOIN u u ON u.k = a.k ORDER BY a.id, u.v",
        "SELECT a.id FROM a a JOIN t t ON t.aid = a.id ORDER BY a.id",
    ],
    "9 explain": [
        "SELECT a.id FROM a a WHERE a.id > 1 ORDER BY a.id LIMIT 2",
    ],
    "10 error codes": [
        "SELECT a.nope FROM a a",
        "SELECT a.id FROM a a WHERE a.n = 5",
    ],
}


def run(tree: pathlib.Path, cases: list) -> dict:
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(tree)!r})\n"
        "import tarn\n"
        "db, out = json.load(open(sys.argv[1])), {}\n"
        "for name, sql in json.load(open(sys.argv[2])):\n"
        "    rec = {}\n"
        "    try:\n"
        "        c = tarn.connect(db); r = c.execute(sql)\n"
        "        rec['rows'] = [[['n',None] if v is None else "
        "(['b',v] if isinstance(v,bool) else (['i',v] if isinstance(v,int) else "
        "(['f',v] if isinstance(v,float) else ['t',v]))) for v in row] for row in r.rows]\n"
        "        rec['processed'] = c.stats.rows_processed\n"
        "    except Exception as exc:\n"
        "        rec['error'] = type(exc).__name__ + ': ' + str(exc)\n"
        "    try:\n"
        "        rec['plan'] = tarn.connect(db).explain(sql)\n"
        "    except Exception as exc:\n"
        "        rec['plan_error'] = type(exc).__name__ + ': ' + str(exc)\n"
        "    out[name] = rec\n"
        "json.dump(out, open(sys.argv[3], 'w'))\n"
    )
    import tempfile

    work = pathlib.Path(tempfile.mkdtemp(prefix="sweep-"))
    (work / "db.json").write_text(json.dumps(DB))
    (work / "cases.json").write_text(json.dumps(cases))
    (work / "run.py").write_text(code)
    done = subprocess.run(
        [
            sys.executable,
            str(work / "run.py"),
            str(work / "db.json"),
            str(work / "cases.json"),
            str(work / "out.json"),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if not (work / "out.json").exists():
        raise SystemExit(f"sweep run failed: {done.stderr[-400:]}")
    return json.loads((work / "out.json").read_text())


JOIN_LINE = re.compile(
    r"^\s*(NestedLoopJoin|HashJoin|MergeJoin|AntiJoin|NullAwareAntiJoin|AntiMatch)"
    r"(?:\s+kind=(inner|left))?\s*$", re.M)


def join_tokens(plan):
    """What a plan specifies: each join's operator and kind, in plan order.

    Section 9 fixes only this much of a plan's text, so a plan finding is judged on
    nothing else.
    """
    if not isinstance(plan, str):
        return None
    return [(m.group(1), m.group(2) or "") for m in JOIN_LINE.finditer(plan)]


def differs(x: dict, y: dict) -> list:
    out = []
    if x.get("error") != y.get("error"):
        out.append("error")
    elif x.get("rows") != y.get("rows"):
        out.append("answer")
    if (join_tokens(x.get("plan")) != join_tokens(y.get("plan"))
            or x.get("plan_error") != y.get("plan_error")):
        out.append("plan")
    return out


def main() -> int:
    verbose = "--verbose" in sys.argv
    cases = [
        (f"{rule} :: {i}", sql)
        for rule, queries in SWEEP.items()
        for i, sql in enumerate(queries)
    ]
    print(
        f"spec sweep: {len(cases)} queries over {len(SWEEP)} rule groups, "
        f"{len(cases) * 2} service calls"
    )

    shipped = run(BUILD / "shipped", cases)
    reference = run(BUILD / "reference", cases)
    variants = {p.name[2:]: run(p, cases) for p in sorted(BUILD.glob("M_*"))}

    caught, flagged = {}, []
    for name, _ in cases:
        kinds = differs(shipped[name], reference[name])
        if not kinds:
            continue
        flagged.append((name, kinds))
        for defect, answers in variants.items():
            if not differs(answers[name], reference[name]):
                caught.setdefault(defect, []).append((name, kinds))

    print(f"\nqueries where shipped and reference differ: {len(flagged)}")
    if verbose:
        for name, kinds in flagged:
            print(f"  {name}  [{', '.join(kinds)}]")

    print(f"\ndefects the sweep catches: {len(caught)} of {len(variants)}")
    for defect in sorted(variants):
        hits = caught.get(defect, [])
        mark = "CAUGHT" if hits else "missed"
        detail = f"  first: {hits[0][0]} [{', '.join(hits[0][1])}]" if hits else ""
        print(f"  {mark:7s} {defect}{detail}")
    print(f"\ntarget is at most 3 caught; this slate: {len(caught)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
