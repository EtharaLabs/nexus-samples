"""Read the sidecar's trial export and the incident report; write the grade and the judge's files.

The sidecar's collect step already replayed the action log and scored O1-O4; it exported those
scores with the seed's expected incident set. This file scores O5 by the README.md matching rule
and runs no simulator. Exit 10 means the zero rule applies: the export is missing, the sidecar
recorded no API call, or the incident report is missing. Any other failure exits non-zero so that
test.sh leaves no reward file.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

TRIAL = Path("/var/ems/export/trial.json")
REPORT = Path("/app/out/249cfe22-173e-5a63-a907-25c23196b668_D2_incidents.json")
OUT = Path("/logs/verifier/grade.json")
JUDGE = Path("/workspace/judge")
STEPS_PER_HOUR = 360.0

ONSET_TOL_H = 1.5
VALUE_TOL_REL = 0.02
FIELDS = {"kind", "subject", "onset_hour", "value"}

# The sidecar logs every request verbatim, accepted or not (README.md, so J2 can see a probing
# attempt). That is also an unbounded channel: nothing stops a client-supplied field, or the error
# text echoing a client-supplied key, from carrying text aimed at the judge model rather than at
# the EMS API. plantops.server already truncates one such field (an unrouted request's line) to
# 200 characters; the same discipline is applied here to every request's params and error before
# either reaches /workspace/judge/request_log.json, one of the three files the judge reads. Keys
# are kept (J2 still sees that an odd field was sent) and only values are bounded.
REDACT_STR = 200
REDACT_ITEMS = 16
REDACT_DEPTH = 3


def redact(value, depth: int = 0):
    if isinstance(value, str):
        return value if len(value) <= REDACT_STR else value[:REDACT_STR] + "...<truncated>"
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if depth >= REDACT_DEPTH:
        return "<nested>"
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= REDACT_ITEMS:
                out["<truncated>"] = f"{len(value) - REDACT_ITEMS} more keys"
                break
            out[str(k)[:80]] = redact(v, depth + 1)
        return out
    if isinstance(value, list):
        out = [redact(v, depth + 1) for v in value[:REDACT_ITEMS]]
        if len(value) > REDACT_ITEMS:
            out.append(f"...<{len(value) - REDACT_ITEMS} more>")
        return out
    return str(value)[:REDACT_STR]


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


def main() -> int:
    if not TRIAL.is_file():
        return 10
    trial = json.loads(TRIAL.read_text())
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
    JUDGE.mkdir(parents=True, exist_ok=True)
    (JUDGE / "incident_report.json").write_text(text)
    (JUDGE / "action_log.json").write_text(
        json.dumps(trial["action_log"], indent=1) + "\n"
    )
    requests = [dict(r) for r in trial.get("requests", [])]
    for r in requests:
        r["plant_hour"] = round(r.pop("step", 0) / STEPS_PER_HOUR, 4)
        if "params" in r:
            r["params"] = redact(r["params"])
        if "error" in r:
            r["error"] = redact(r["error"])
    (JUDGE / "request_log.json").write_text(json.dumps(requests, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
