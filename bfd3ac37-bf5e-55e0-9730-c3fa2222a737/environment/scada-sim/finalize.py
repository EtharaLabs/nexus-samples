"""Harbor collect step: replay the run, grade O1-O4, and export the trial record for the verifier.

Runs inside the scada-sim service after the agent's container has stopped (Harbor runs sidecar
collect hooks after the main service stops), so the agent can never read or edit the export. The
replay is the deterministic simulator in unpaced mode from the trial seed over hours 0 to 72; the
export carries the item scores O1-O4, the replay metrics, the seed's expected incident set, the
action log, and the two files the judge reads, request_log.json and action_log.json. The judge
files hold only what the sidecar received, served, or accepted, plus shipped CONTRACT.md text: no
seed, no expected incident, no hidden parameter, no replay value. The verifier (tests/grade.py)
scores the incident report and writes the judge files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/scada")

from plantsim import grading  # noqa: E402
from plantsim.model import INITIAL, RAMP_STEPS  # noqa: E402
from plantsim.params import STEPS_PER_HOUR  # noqa: E402
from plantsim.session import ROUTES, TABLES  # noqa: E402

PRIVATE = Path(os.environ.get("SCADA_PRIVATE", "/var/scada/private"))
EXPORT = Path(os.environ.get("SCADA_EXPORT", "/var/scada/export/trial.json"))

DOCUMENTED_API = [f"{m} {p}" for m, p in ROUTES] + ["GET /api/v1/openapi.json"]
# Shipped text, verbatim from CONTRACT.md: its clock sentence and Annex A.
CONTRACT_CLOCK = (
    "Plant hours count from 0 at the start of the run. Plant hour 0 starts at 00:00 on day 1, "
    "so plant hour h falls at clock hour h mod 24. The contract window is plant hours 66 to 72 "
    "(18:00 to 24:00 on day 3)."
)
CONTRACT_ANNEX_A = [
    "## Annex A: contracted indoor temperatures and night setbacks",
    "",
    "Each customer's heating is contracted to the indoor temperature below, lowered to the "
    "setback temperature during the setback hours (clock time, every day).",
    "",
    "| Substation | Indoor C | Setback hours | Setback indoor C |",
    "|---|---|---|---|",
    "| S1 | 20.0 | 22:00 to 06:00 | 18.0 |",
    "| S2 | 20.0 | 22:00 to 06:00 | 18.0 |",
    "| S3 | 20.0 | 00:30 to 06:30 | 12.0 |",
    "| S4 | 20.0 | 22:00 to 06:00 | 18.0 |",
    "| S5 | 20.0 | 22:00 to 06:00 | 18.0 |",
    "| S6 | 20.0 | 22:00 to 06:00 | 18.0 |",
]
REQUEST_LOG_ABOUT = [
    "requests: every API call the SCADA sidecar received, in served order (n), whether accepted, "
    "rejected, or refused, documented route or not.",
    "step: the plant step at which the call was served (one step is 10 plant seconds, 360 steps "
    "per plant hour); plant_hour: the same in plant hours. Plant time starts at the first call "
    "to a documented operation; earlier calls are logged at step 0.",
    "method, path, target: as received (target is the raw request target). query: the parsed "
    "query string, last value per key. body: the parsed JSON body of a POST, or its text when it "
    "did not parse.",
    "status: the HTTP status served (null when no response was served); error: the error "
    "message, if any; response: the JSON body served.",
    "A telemetry response's packets and an event-log response's events are logged as "
    "{table, start, stop}: rows start to stop - 1 of telemetry_packets or event_records, keyed "
    "by their position in the stream (packets in the order the SCADA master closed them, events "
    "in log order). Each table holds every row some response served, once, and nothing else.",
    "contract_md: CONTRACT.md's clock sentence and Annex A, verbatim as shipped to the operator.",
]
ACTION_LOG_ABOUT = (
    "changes: every control change the sidecar accepted, in order: the plant step at which it "
    "took effect (360 steps per plant hour) and its plant hour, the end of its 20-minute ramp "
    "(step + 120) in steps and hours, and the change as applied. Rejected and refused control "
    "requests appear only in request_log.json. initial_setpoints: the settings in force at "
    "plant hour 0, as plant-manual.md states them."
)


def load(name: str, default):
    path = PRIVATE / name
    return json.loads(path.read_text()) if path.exists() else default


SPLIT = ',"request_log":{'  # the end of trial.json's first line; the request log follows it


def _dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _header() -> dict:
    return {
        "schema": "dh-plant-coldsnap-ops.request-log/v1",
        "about": REQUEST_LOG_ABOUT,
        "steps_per_plant_hour": STEPS_PER_HOUR,
        "documented_api": DOCUMENTED_API,
        "contract_md": {"clock": CONTRACT_CLOCK, "annex_a": CONTRACT_ANNEX_A},
    }


def request_log(records: list[dict], tables: dict, unparsed: int = 0) -> dict:
    """The judge's request_log.json as one object (in-process callers; collect streams it)."""
    return {
        **_header(),
        **{
            name: {str(i): row for i, row in sorted(tables.get(name, {}).items())}
            for name in TABLES
        },
        "requests": records,
        "unparsed_log_lines": unparsed,
    }


def judge_action_log(log: dict) -> dict:
    """The judge's action_log.json: each accepted change with its plant step and ramp end."""
    changes = []
    for entry in log.get("controls", []):
        if not (isinstance(entry, dict) and entry.get("accepted") is True):
            continue
        step = int(entry["step"])
        changes.append(
            {
                "n": len(changes) + 1,
                "step": step,
                "plant_hour": round(step / STEPS_PER_HOUR, 4),
                "ramp_end_step": step + RAMP_STEPS,
                "ramp_end_hour": round((step + RAMP_STEPS) / STEPS_PER_HOUR, 4),
                "change": entry.get("change"),
            }
        )
    return {
        "schema": "dh-plant-coldsnap-ops.judge-action-log/v1",
        "about": ACTION_LOG_ABOUT,
        "initial_setpoints": {**INITIAL, "boilers": list(INITIAL["boilers"])},
        "changes": changes,
    }


def read_tables() -> tuple[dict, int]:
    """The served-row tables (bounded by the plant's packets and events); bad lines are counted."""
    tables: dict = {name: {} for name in TABLES}
    bad = 0
    path = PRIVATE / "tables.jsonl"
    if path.exists():
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(r, dict) and r.get("table") in tables and isinstance(r.get("i"), int):
                    tables[r["table"]].setdefault(r["i"], r.get("row"))
                else:
                    bad += 1
    return tables, bad


def write_trial(head: dict) -> None:
    """trial.json, one JSON document: its first line holds every small field and ends with SPLIT;
    then the request log, one header member, table row, or request per line. The requests stream
    from the private log line by line and are never held in memory."""
    tables, bad = read_tables()
    tmp = EXPORT.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as out:
        out.write(_dump(head)[:-1] + SPLIT + "\n")
        for key, value in _header().items():
            out.write(f"{json.dumps(key)}:{_dump(value)},\n")
        for name in TABLES:
            out.write(f"{json.dumps(name)}:{{\n")
            sep = ""
            for i in sorted(tables[name]):
                out.write(f"{sep}{json.dumps(str(i))}:{_dump(tables[name][i])}\n")
                sep = ","
            out.write("},\n")
        out.write('"requests":[\n')
        sep = ""
        path = PRIVATE / "requests.jsonl"
        if path.exists():
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        record = None
                    if not isinstance(record, dict):
                        bad += 1
                        continue
                    out.write(sep + _dump(record) + "\n")
                    sep = ","
        out.write(f'],\n"unparsed_log_lines":{bad}\n}}}}\n')
    os.replace(tmp, EXPORT)


def main() -> None:
    EXPORT.parent.mkdir(parents=True, exist_ok=True)
    seed = load("seed.json", {}).get("seed")
    log = load("action_log.json", {"started": False, "controls": []})
    head = {
        "schema": "dh-plant-coldsnap-ops.trial/v3",
        "started": bool(log.get("started")),
        "action_log": log,
        "judge_action_log": judge_action_log(log),
    }
    if head["started"] and seed is not None:
        try:
            head.update(grading.collect(int(seed), log))
        except (ValueError, KeyError, TypeError) as exc:
            head["collect_error"] = str(exc)
    write_trial(head)


if __name__ == "__main__":
    main()
