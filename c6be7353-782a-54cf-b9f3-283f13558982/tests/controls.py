"""Controls on the grader: which items each kind of submission passes.

The reward is 1 only when every item passes. The reference passes all of them with
the call log its own investigation leaves; every other control must fail at least
the item it was built to break. The reference log is made by replaying the reference
plan through the query service's own code, so digests and outcomes are the real ones.
"""

import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRADE = ROOT / "tests" / "grade.py"
sys.path.insert(0, str(ROOT / "solution"))
import reference_probe as rp  # noqa: E402

REF = rp.findings()
MAIN = json.loads((ROOT / "solution" / "probe_main.json").read_text(encoding="utf-8"))


def reference_log(skip_boundary: bool = False) -> list:
    log = pathlib.Path(tempfile.mkdtemp(prefix="bb-ctl-log-")) / "calls.jsonl"
    os.environ["TARND_LOG"] = str(log)
    tarnd = ROOT / "environment" / "tarnd"
    sys.path[:0] = [str(tarnd), str(tarnd / "engine")]
    spec = importlib.util.spec_from_file_location(
        f"server_{skip_boundary}", tarnd / "server.py"
    )
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    boundaries = {
        (json.dumps(rp.boundary(p)[1], sort_keys=True), rp.boundary(p)[2])
        for p in rp.PROBES.values()
    }
    for verb, database, sql in rp.plan():
        if skip_boundary and (json.dumps(database, sort_keys=True), sql) in boundaries:
            continue
        server.handle(verb, {"database": json.loads(json.dumps(database)), "sql": sql})
    return [json.loads(line) for line in log.read_text().splitlines()]


def score(findings, log_lines):
    work = pathlib.Path(tempfile.mkdtemp(prefix="bb-ctl-"))
    (work / "f.json").write_text(json.dumps(findings))
    log = work / "calls.jsonl"
    log.write_text("".join(json.dumps(x) + "\n" for x in log_lines))
    done = subprocess.run(
        [
            sys.executable,
            str(GRADE),
            "--findings",
            str(work / "f.json"),
            "--log",
            str(log),
            "--out",
            str(work / "g.json"),
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if not (work / "g.json").exists():
        return None, f"grade failed: {done.stderr[-200:]}"
    return json.loads((work / "g.json").read_text()), None


def with_change(index: int, change) -> list:
    out = copy.deepcopy(REF)
    change(out[index])
    return out


def main() -> int:
    log = reference_log()
    no_boundary = reference_log(skip_boundary=True)

    def extra_row(entry):
        entry["database"]["tables"]["a"]["rows"].append([9])

    def unused_column(entry):
        table = entry["database"]["tables"]["o"]
        table["columns"].append({"name": "spare", "type": "TEXT", "nullable": True})
        for row in table["rows"]:
            row.append("x")

    def extra_item(entry):
        entry["sql"] = entry["sql"].replace(
            "SELECT a.id FROM", "SELECT a.id, b.id FROM", 1
        )

    def bad_value(entry):
        entry["database"]["tables"]["t"]["rows"][0][0] = "one"

    cases = {
        "reference, its own call log": (REF, log, set()),
        "reference, no call log": (REF, [], {"reproduced", "boundary_shown"}),
        "reference, no boundary calls": (REF, no_boundary, {"boundary_shown"}),
        "P1 with a row it does not need": (
            with_change(0, extra_row),
            log,
            {"rows_minimal"},
        ),
        "P3 with a column it does not need": (
            with_change(2, unused_column),
            log,
            {"schema_minimal"},
        ),
        "P6 with a second select item": (
            with_change(5, extra_item),
            log,
            {"statement_minimal"},
        ),
        "P5 with an invalid database": (with_change(4, bad_value), log, {"gate"}),
        "empty findings": ([], log, {"P1_join_depth_conversion", "rows_minimal"}),
        "one defect only": (REF[:1], log, {"P2_crosstype_guard"}),
        "every section, generic queries": (
            [
                {
                    "section": s,
                    "kind": "answer",
                    "database": MAIN,
                    "sql": "SELECT a.id FROM a a ORDER BY a.id",
                }
                for s in ("2", "3", "4", "5", "6.3", "7", "8")
            ],
            log,
            {"gate"},
        ),
        "reports a decoy": (
            REF[:6]
            + [
                {
                    "section": "4.1",
                    "kind": "answer",
                    "database": MAIN,
                    "sql": "SELECT a.id FROM a a WHERE a.k NOT IN "
                    "(SELECT u.k FROM u u WHERE u.k > 99999) ORDER BY a.id",
                }
            ],
            log,
            {"gate"},
        ),
        "eight entries": (REF + [REF[0]], log, {"gate"}),
        "right defect, wrong section": (
            [dict(REF[0], section="9")] + REF[1:],
            log,
            {"P1_join_depth_conversion"},
        ),
        "right defect, wrong kind": (
            [dict(REF[0], kind="answer")] + REF[1:],
            log,
            {"P1_join_depth_conversion"},
        ),
    }
    over = log + [{"call": 251, "verb": "execute", "refused": True}]
    cases["reference but budget exhausted"] = (REF, over, {"gate"})

    ok = True
    print(f"{'control':36s} {'passed':>7s} {'reward':>7s}  failed items")
    for label, (findings, lines, must_fail) in cases.items():
        report, err = score(findings, lines)
        if err:
            print(f"{label:36s} {err}")
            ok = False
            continue
        failed = {k for k, v in report["items"].items() if v < 1.0}
        if not report["gate"]["ok"]:
            failed.add("gate")
        reward = int(not failed)
        expected = (not must_fail and reward == 1) or (
            must_fail and must_fail <= failed
        )
        ok &= expected
        shown = ", ".join(sorted(failed))[:70] or "-"
        print(
            f"{label:36s} {len(report['items']) - len(failed - {'gate'}):>4d}/12 {reward:>7d}  "
            f"{shown}{'' if expected else '   <-- UNEXPECTED'}"
        )
    print(f"\nevery control behaves as designed: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
