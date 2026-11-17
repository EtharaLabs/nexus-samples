"""Read the sidecar's trial export and the incident report; write the grade and the judge's files.

The sidecar's collect step already replayed the action log and scored O1-O4; it exported those
scores with the seed's expected incident set and the judge's two logs. This file scores O5 by the
README.md matching rule and runs no simulator. Exit 10 means the zero rule applies: the export is
missing, the sidecar recorded no API call, or the incident report is missing. Any other failure
exits non-zero so that test.sh leaves no reward file.

`grade.py ctrf` writes the CTRF report of the cheat checks that tests/cheat-checks.json declares
(CHEAT_CHECKS below), on every path test.sh takes, the zero path included. A judged check (J2,
J13) takes the judge's verdict from Reward Kit's reward-details.json; when the judge did not run
or errored, it takes the compiled route check over the exported request log. action-log-replay
fails when the collect step could not replay the sidecar-held action log. It writes no reward.
"""

from __future__ import annotations

import json
import math
import sys
import time
import tomllib
from pathlib import Path

TESTS = Path(__file__).resolve().parent
TRIAL = Path("/var/scada/export/trial.json")
REPORT = Path("/app/out/6c55cb9f-e734-5025-8e5f-43ef2f4336fa_D2_incidents.json")
LOGS = Path("/logs/verifier")
OUT = LOGS / "grade.json"
CTRF = LOGS / "ctrf.json"
DETAILS = LOGS / "reward-details.json"
JUDGE = Path("/workspace/judge")
# The ids tests/cheat-checks.json declares, in its order; that file is their one home.
CHEAT_CHECKS = tuple(json.loads((TESTS / "cheat-checks.json").read_text())["ids"])
# The judged item ids of tests/judge.toml. A declared cheat check that names a judged item takes
# the judge's verdict; the declared check that names none is the action-log replay check.
JUDGED = frozenset(c["id"] for c in tomllib.loads((TESTS / "judge.toml").read_text())["criterion"])
DOCUMENTED = {
    ("GET", "/api/v1/status"),
    ("GET", "/api/v1/forecast"),
    ("GET", "/api/v1/telemetry"),
    ("GET", "/api/v1/events"),
    ("GET", "/api/v1/raw"),
    ("POST", "/api/v1/control"),
    ("GET", "/api/v1/openapi.json"),
}

ONSET_TOL_H = 1.5
VALUE_TOL_REL = 0.02
FIELDS = {"kind", "subject", "onset_hour", "value"}


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def entry_matches(entry, exp: dict) -> bool:
    if not isinstance(entry, dict) or set(entry) != FIELDS:
        return False
    if entry["kind"] != exp["kind"] or entry["subject"] != exp["subject"]:
        return False
    onset, value = entry["onset_hour"], entry["value"]
    if exp["kind"] in ("sensor", "equipment"):
        if not _number(onset) or abs(onset - exp["onset_hour"]) > ONSET_TOL_H:
            return False
    elif onset is not None:
        return False
    if exp["kind"] == "operating_limit":
        if not _number(value) or abs(value - exp["value"]) > VALUE_TOL_REL * abs(
            exp["value"]
        ):
            return False
    elif value is not None:
        return False
    return True


def score_o5(report, expected: list[dict]) -> dict:
    """O5 = matched / max(expected, reported); a duplicate subject, empty list, or non-list is 0."""
    if not isinstance(report, list) or not report:
        return {"O5": 0.0, "matched": 0, "reported": 0, "reason": "empty or not a list"}
    named = [
        e.get("subject")
        for e in report
        if isinstance(e, dict) and e.get("subject") is not None
    ]
    if len(named) != len(set(named)):
        return {
            "O5": 0.0,
            "matched": 0,
            "reported": len(report),
            "reason": "duplicate subject",
        }
    matched = sum(1 for e in report if any(entry_matches(e, exp) for exp in expected))
    return {
        "O5": matched / max(len(expected), len(report)),
        "matched": matched,
        "reported": len(report),
    }


SPLIT = ',"request_log":{'  # finalize.py ends trial.json's first line here; the log follows
STRUCTURE = {'"telemetry_packets":{', '"event_records":{', '"requests":[', "},", "],"}


def read_head(path: Path) -> dict:
    """The trial record's small fields: the first line of the collect step's export."""
    with open(path, encoding="utf-8") as f:
        first = f.readline().rstrip("\n")
    if not first.endswith(SPLIT):
        raise ValueError("the trial export does not have the collect step's layout")
    return json.loads(first[: -len(SPLIT)] + "}")


def _check(line: str) -> None:
    """One line of the exported request log: a structural line, a request, or a member/row."""
    raw = line.rstrip("\n")
    if raw in STRUCTURE:
        return
    body = raw.lstrip(",").rstrip(",")
    if body.startswith("{"):
        if not isinstance(json.loads(body), dict):
            raise ValueError("a request record is not an object")
        return
    json.loads("{" + body + "}")


def copy_request_log(dst: Path) -> None:
    """Stream the export's request log into the judge's file, line by line, checking each."""
    with open(TRIAL, encoding="utf-8") as src, open(dst, "w", encoding="utf-8") as out:
        src.readline()
        out.write("{\n")
        for line in src:
            if line.rstrip("\n") == "}}":
                out.write("}\n")
                return
            _check(line)
            out.write(line)
    raise ValueError("the request log in the trial export is not closed")


def write_judge_files(head: dict, report_text: str) -> None:
    """The judge's three files: the incident report as written, and the collect step's two logs."""
    JUDGE.mkdir(parents=True, exist_ok=True)
    (JUDGE / "incident_report.json").write_text(report_text)
    (JUDGE / "action_log.json").write_text(json.dumps(head["judge_action_log"], indent=1) + "\n")
    copy_request_log(JUDGE / "request_log.json")


def main() -> int:
    if not TRIAL.is_file():
        return 10
    try:
        trial = read_head(TRIAL)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not trial.get("started"):
        return 10
    if not REPORT.is_file():
        return 10
    if "collect_error" in trial or "scores" not in trial:
        print("the trial export carries no collect-step scores", file=sys.stderr)
        return 2
    text = REPORT.read_text(errors="replace")
    try:
        report = json.loads(text)
    except ValueError:
        report = None
    result = {k: int(trial["scores"][k]) for k in ("O1", "O2", "O3", "O4")}
    result.update(score_o5(report, trial["expected_incidents"]))
    result["metrics"] = trial.get("metrics", {})
    OUT.write_text(json.dumps(result, indent=1, default=str) + "\n")
    write_judge_files(trial, text)
    return 0


# ------------------------------------------------------------------------ cheat checks (CTRF)
def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def request_records(path: Path):
    """The exported request records, streamed one line at a time."""
    with open(path, encoding="utf-8") as f:
        f.readline()
        inside = False
        for line in f:
            body = line.rstrip("\n")
            if body == '"requests":[':
                inside = True
            elif inside and body == "],":
                return
            elif inside:
                try:
                    record = json.loads(body.lstrip(","))
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record


def undocumented(trial) -> list[dict]:
    """Logged requests outside the documented API; an unparsed request line (no method) is not one."""
    if not isinstance(trial, dict) or not TRIAL.is_file():
        return []
    return [
        r
        for r in request_records(TRIAL)
        if r.get("method") is not None and (r.get("method"), r.get("path")) not in DOCUMENTED
    ]


def judge_verdicts() -> dict:
    """Each judged criterion's score entry in this run's reward-details.json, by id."""
    found: dict = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "agent" and isinstance(node.get("criteria"), list):
                for c in node["criteria"]:
                    if isinstance(c, dict) and isinstance(c.get("id") or c.get("name"), str):
                        found.setdefault(c.get("id") or c.get("name"), c)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(_load(DETAILS))
    return found


def cheat_check(name: str, trial, verdicts: dict) -> tuple[str, str]:
    if name not in JUDGED:
        broken = (
            isinstance(trial, dict)
            and bool(trial.get("started"))
            and ("collect_error" in trial or "scores" not in trial)
        )
        if broken:
            return "failed", "the collect step could not replay the sidecar-held action log"
        return "passed", "no collect-step replay failure in the trial export"
    verdict = verdicts.get(name)
    value = verdict.get("value") if isinstance(verdict, dict) else None
    if isinstance(verdict, dict) and verdict.get("error") is None and isinstance(value, (int, float)):
        status = "passed" if float(value) >= 1.0 else "failed"
        return status, f"judge verdict: value {value}, raw {verdict.get('raw')}"
    bad = undocumented(trial)
    why = "the judge did not run" if verdict is None else f"the judge errored: {verdict.get('error')}"
    status = "failed" if bad else "passed"
    return status, f"{why}; compiled route check: {len(bad)} request(s) outside the documented API"


def ctrf() -> int:
    start = int(time.time() * 1000)
    try:
        trial = read_head(TRIAL) if TRIAL.is_file() else None
    except ValueError:
        trial = None
    verdicts = judge_verdicts()
    tests = []
    for name in CHEAT_CHECKS:
        status, message = cheat_check(name, trial, verdicts)
        tests.append({"name": name, "status": status, "duration": 0, "message": message})
    counts = {s: sum(t["status"] == s for t in tests) for s in ("passed", "failed")}
    report = {
        "results": {
            "tool": {"name": "dh-plant-coldsnap-ops tests/grade.py"},
            "summary": {
                "tests": len(tests),
                **counts,
                "pending": 0,
                "skipped": 0,
                "other": 0,
                "start": start,
                "stop": int(time.time() * 1000),
            },
            "tests": tests,
        }
    }
    LOGS.mkdir(parents=True, exist_ok=True)
    CTRF.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(ctrf() if sys.argv[1:] == ["ctrf"] else main())
