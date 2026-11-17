"""Harbor collect step: replay the run, grade O1-O4, and export the trial record for the verifier.

Runs inside the simulator sidecar after the agent's container has stopped (Harbor runs sidecar
collect hooks after the main service stops), so the agent can never read or edit the export. The
replay is the deterministic simulator in unpaced mode from the trial seed over hours 0 to 72; the
export carries the item scores O1-O4, the replay metrics, the seed's expected incident set, the
action log, and the request log. The verifier (tests/grade.py) scores the incident report.

Run as ``python3 -m plantops.finalize``; the member module's ``collect(seed, log)`` returns
``{"scores": {O1..O4}, "metrics": {...}, "expected_incidents": [...]}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .server import load_member, private_dir


def main() -> None:
    member = load_member()
    private = private_dir(member)
    export = Path(os.environ.get("PLANTOPS_EXPORT", member.EXPORT_PATH))

    def load(name: str, default):
        path = private / name
        return json.loads(path.read_text()) if path.exists() else default

    export.parent.mkdir(parents=True, exist_ok=True)
    seed = load("seed.json", {}).get("seed")
    log = load("action_log.json", {"started": False, "controls": []})
    trial = {
        "schema": member.TRIAL_SCHEMA,
        "started": bool(log.get("started")),
        "action_log": log,
        "requests": load("requests.json", []),
    }
    if trial["started"] and seed is not None:
        try:
            trial.update(member.collect(int(seed), log))
        except (ValueError, KeyError, TypeError) as exc:
            trial["collect_error"] = str(exc)
    export.write_text(json.dumps(trial, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
