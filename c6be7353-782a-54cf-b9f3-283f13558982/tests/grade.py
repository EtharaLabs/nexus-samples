"""The grader.

Each finding the agent reports is re-run against the shipped engine, the reference,
and the shipped engine with exactly one defect repaired. A finding belongs to defect
k when the shipped engine and the reference differ on it, and repairing only k makes
that difference go away.

The precision gate is narrow on purpose. A false claim zeroes every item: a finding
that shows nothing, a finding that needs two repairs to disappear, a finding that
reports behaviour the specification requires, a finding whose database is not valid,
more than seven entries, or a call refused because the budget was spent.

Five more items judge the report and the investigation behind it. A finding is
minimal when no single-element reduction of it (reduce.py) is still a finding for
the same defect, split into rows, schema (tables, columns, indexes) and statement.
It is reproduced when the call log holds its own statement on its own database, sent
with the verb its kind needs, and it shows its boundary when the log also holds at
least one of its single-element reductions sent the same way.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import dbshape  # noqa: E402

# The sections whose rule each defect breaks; citing any one of them is credited. P4
# breaks the grammar of section 2, which admits IN in an ON, and with it the result
# section 4.1 gives that IN. P5 breaks the index order of section 7, and with it the
# ORDER BY that section 6.6 answers by reading through that index.
SECTIONS = {
    "P1_join_depth_conversion": ("6.3",),
    "P2_crosstype_guard": ("8",),
    "P3_nested_scope_collation": ("5",),
    "P4_in_inside_on": ("2", "4.1"),
    "P5_nocase_index_order": ("7", "6.6"),
    "P6_split_anti_leg_depth": ("6.3",),
    "P7_coalesce_collation": ("5",),
}
EXPECTED = 7
KINDS = ("answer", "plan", "error")
# Seconds for one engine run over a batch of cases. grade.py makes at most 18 runs, so
# together with the judge's cap in test.sh the verifier stays inside its timeout_sec.
ENGINE_TIMEOUT = 60
VERB = {"plan": "explain", "answer": "execute", "error": "execute"}
REPORT_ITEMS = (
    "rows_minimal",
    "schema_minimal",
    "statement_minimal",
    "reproduced",
    "boundary_shown",
)

# A decoy needs no list of its own. Behaviour the specification requires is
# behaviour the shipped engine and the reference agree on, so a finding that
# reports one shows no difference and is a false claim by that rule already.

RUNNER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import tarn
out = []
for case in json.load(open(sys.argv[2])):
    rec = {}
    try:
        conn = tarn.connect(case["database"])
        result = conn.execute(case["sql"])
        rec["rows"] = [[["n", None] if v is None else
                        (["b", v] if isinstance(v, bool) else
                         (["i", v] if isinstance(v, int) else
                          (["f", v] if isinstance(v, float) else ["t", v])))
                        for v in row] for row in result.rows]
    except Exception as exc:
        code = getattr(type(exc), "code", None)
        rec["error"] = code or f"{type(exc).__name__}"
    try:
        rec["plan"] = tarn.connect(case["database"]).explain(case["sql"])
    except Exception as exc:
        rec["plan_error"] = getattr(type(exc), "code", None) or type(exc).__name__
    out.append(rec)
json.dump(out, open(sys.argv[3], "w"))
"""


JOIN_LINE = re.compile(
    r"^\s*(NestedLoopJoin|HashJoin|MergeJoin|AntiJoin|NullAwareAntiJoin|AntiMatch)"
    r"(?:\s+kind=(inner|left))?\s*$",
    re.M,
)


def join_tokens(plan):
    """What a plan specifies: each join's operator and kind, in plan order.

    Section 9 fixes only this much of a plan's text, so a plan finding is judged on
    nothing else.
    """
    if not isinstance(plan, str):
        return None
    return [(m.group(1), m.group(2) or "") for m in JOIN_LINE.finditer(plan)]


def observables(x: dict, y: dict) -> list:
    out = []
    if x.get("error") != y.get("error"):
        out.append("error")
    elif x.get("rows") != y.get("rows"):
        out.append("answer")
    if join_tokens(x.get("plan")) != join_tokens(y.get("plan")) or x.get(
        "plan_error"
    ) != y.get("plan_error"):
        out.append("plan")
    return out


def run(tree: pathlib.Path, cases: list, work: pathlib.Path, tag: str) -> list:
    script = work / "runner.py"
    script.write_text(RUNNER, encoding="utf-8")
    src = work / f"cases-{tag}.json"
    src.write_text(json.dumps(cases), encoding="utf-8")
    out = work / f"out-{tag}.json"
    try:
        done = subprocess.run(
            [sys.executable, str(script), str(tree), str(src), str(out)],
            capture_output=True,
            text=True,
            timeout=ENGINE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{tag}: engine run exceeded {ENGINE_TIMEOUT} s")
    if not out.exists():
        raise SystemExit(f"{tag}: engine run failed: {done.stderr[-400:]}")
    return json.loads(out.read_text())


def run_all(build: pathlib.Path, cases: list, label: str) -> tuple:
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"bb-{label}-"))
    shipped = run(build / "shipped", cases, work, "shipped")
    reference = run(build / "reference", cases, work, "reference")
    variants = {
        p.name[2:]: run(p, cases, work, p.name) for p in sorted(build.glob("M_*"))
    }
    return shipped, reference, variants


def owners_of(i: int, shipped: list, reference: list, variants: dict) -> tuple:
    seen = observables(shipped[i], reference[i])
    owners = (
        [
            d
            for d, answers in variants.items()
            if not observables(answers[i], reference[i])
        ]
        if seen
        else []
    )
    return seen, owners


def load_findings(path: pathlib.Path) -> tuple:
    if not path.exists():
        return [], ["findings.json is missing"]
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"findings.json does not parse: {exc}"]
    if not isinstance(body, list):
        return [], ["findings.json is not a list"]
    problems = []
    clean = []
    for i, entry in enumerate(body):
        if not isinstance(entry, dict):
            problems.append(f"entry {i} is not an object")
            continue
        missing = [k for k in ("section", "kind", "database", "sql") if k not in entry]
        if missing:
            problems.append(f"entry {i} is missing {', '.join(missing)}")
            continue
        if not isinstance(entry["sql"], str):
            problems.append(f"entry {i} has a sql that is not a string")
            continue
        bad = dbshape.problem(entry["database"])
        if bad is not None:
            problems.append(f"entry {i}: the database is not valid: {bad}")
            continue
        clean.append(entry)
    return clean, problems


def load_log(log: pathlib.Path) -> list:
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def calls_used(entries: list) -> tuple:
    used = refused = 0
    for entry in entries:
        if entry.get("refused"):
            refused += 1
        else:
            used = max(used, int(entry.get("call", 0)))
    return used, refused


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--build", default=str(ROOT / "tests" / "build"))
    ap.add_argument("--log", default="")
    ap.add_argument("--budget", type=int, default=250)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    build = pathlib.Path(args.build)
    sys.path.insert(0, str(build / "reference"))
    import reduce as R  # noqa: E402  (cuts statements on the engine's own lexer)
    from tarn import parse as P  # noqa: E402

    def shape(sql):
        try:
            return repr(P.parse(sql))
        except Exception:
            return None

    findings, problems = load_findings(pathlib.Path(args.findings))
    report = {"items": {}, "gate": {}, "findings": []}

    log_entries = load_log(pathlib.Path(args.log)) if args.log else []
    used, refused = calls_used(log_entries)
    report["gate"]["calls_used"] = used
    report["gate"]["calls_refused"] = refused

    false_claims = list(problems)
    if len(findings) > EXPECTED:
        false_claims.append(
            f"{len(findings)} entries reported; at most {EXPECTED} are allowed"
        )
    if refused:
        false_claims.append(
            f"the call budget was exhausted and {refused} call(s) were refused"
        )

    credited = {}
    owner = {}
    if findings:
        shipped, reference, variants = run_all(build, findings, "grade")
        for i, entry in enumerate(findings):
            seen, owners = owners_of(i, shipped, reference, variants)
            record = {
                "index": i,
                "claimed_section": str(entry.get("section")),
                "claimed_kind": str(entry.get("kind")),
                "observed": seen,
                "owners": owners,
            }
            if not seen:
                record["verdict"] = "false: shows no difference"
                false_claims.append(
                    f"entry {i} shows no difference between the engines"
                )
            elif len(owners) != 1:
                record["verdict"] = (
                    "false: no single defect explains it"
                    if not owners
                    else "false: needs more than one repair"
                )
                false_claims.append(
                    f"entry {i} is explained by {len(owners)} defects, not one"
                )
            else:
                defect = owners[0]
                owner[i] = defect
                want_section = SECTIONS[defect]
                kind_ok = str(entry.get("kind")) in seen
                section_ok = str(entry.get("section")).strip() in want_section
                record["verdict"] = (
                    "credited"
                    if (kind_ok and section_ok)
                    else ("real defect, citation wrong")
                )
                record["defect"] = defect
                if kind_ok and section_ok:
                    credited[defect] = True
                else:
                    record["why"] = (
                        f"section claimed {entry.get('section')}, required "
                        f"{' or '.join(want_section)}; "
                        f"kind claimed {entry.get('kind')}, observed {seen}"
                    )
            report["findings"].append(record)

    # Every single-element reduction of every finding, for minimality and boundary.
    reductions = {}
    for i, entry in enumerate(findings):
        found = []
        for label, db in R.database_reductions(entry["database"]):
            if dbshape.problem(db) is None:
                category = "rows" if label.startswith("row ") else "schema"
                found.append((category, label, db, entry["sql"]))
        try:
            statement_cuts = R.statement_reductions(entry["sql"])
        except Exception:  # a statement the engine's own lexer rejects has no reductions
            statement_cuts = []
        for label, sql in statement_cuts:
            found.append(("statement", label, entry["database"], sql))
        reductions[i] = found

    minimal_faults = {
        i: {"rows": [], "schema": [], "statement": []} for i in range(len(findings))
    }
    flat = [(i, red) for i in owner for red in reductions[i]]
    if flat:
        cases = [{"database": red[2], "sql": red[3]} for _, red in flat]
        r_shipped, r_reference, r_variants = run_all(build, cases, "reduce")
        for j, (i, (category, label, _, _)) in enumerate(flat):
            seen, owners = owners_of(j, r_shipped, r_reference, r_variants)
            if seen and owners == [owner[i]]:
                minimal_faults[i][category].append(label)

    logged = {}
    for entry in log_entries:
        if entry.get("refused") or not isinstance(entry.get("sql"), str):
            continue
        key = shape(entry["sql"])
        if key is not None:
            logged.setdefault((entry.get("verb"), entry.get("database")), set()).add(
                key
            )

    def was_run(verb, database, sql) -> bool:
        return verb is not None and shape(sql) in logged.get(
            (verb, dbshape.digest(database)), set()
        )

    reproduced, boundary = {}, {}
    for i, entry in enumerate(findings):
        verb = VERB.get(str(entry.get("kind")))
        reproduced[i] = was_run(verb, entry["database"], entry["sql"])
        boundary[i] = next(
            (label for _, label, db, sql in reductions[i] if was_run(verb, db, sql)),
            None,
        )
        if i < len(report["findings"]):
            rec = report["findings"][i]
            rec["not_minimal"] = {k: v for k, v in minimal_faults[i].items() if v}
            rec["reproduced"] = reproduced[i]
            rec["boundary_call"] = boundary[i]

    report["gate"]["false_claims"] = false_claims
    report["gate"]["ok"] = not false_claims
    clear = not false_claims and bool(findings)
    for defect in SECTIONS:
        report["items"][defect] = (
            1.0 if (not false_claims and credited.get(defect)) else 0.0
        )
    every = range(len(findings))
    checks = {
        "rows_minimal": all(not minimal_faults[i]["rows"] for i in every),
        "schema_minimal": all(not minimal_faults[i]["schema"] for i in every),
        "statement_minimal": all(not minimal_faults[i]["statement"] for i in every),
        "reproduced": all(reproduced[i] for i in every),
        "boundary_shown": all(boundary[i] is not None for i in every),
    }
    for name in REPORT_ITEMS:
        report["items"][name] = 1.0 if (clear and checks[name]) else 0.0
    report["compiled"] = sum(report["items"].values()) / len(report["items"])

    pathlib.Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"compiled items passed: {sum(1 for v in report['items'].values() if v >= 1.0)}"
        f"/{len(report['items'])}  gate_ok={report['gate']['ok']}  calls_used={used}"
    )
    for name, score in report["items"].items():
        print(f"  {name:30s} {score:.0f}")
    for rec in report["findings"]:
        notes = []
        if rec.get("not_minimal"):
            notes.append(
                "not minimal: "
                + "; ".join(
                    f"{k}: {', '.join(v)}" for k, v in rec["not_minimal"].items()
                )
            )
        if not rec.get("reproduced"):
            notes.append("not reproduced in the call log")
        if rec.get("boundary_call") is None:
            notes.append("no boundary call in the log")
        if notes:
            print(
                f"  entry {rec['index']} ({rec.get('defect', rec.get('verdict'))}): "
                + " | ".join(notes)
            )
    for claim in false_claims[:6]:
        print(f"  FALSE CLAIM: {claim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
