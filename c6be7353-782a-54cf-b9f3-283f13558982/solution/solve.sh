#!/bin/bash
# Reference solution: replay every call of solution/reference_probe.py through tarn-cli
# (the probes, then each minimal finding and one boundary variant of it), so the call
# log holds the reproduction and boundary calls the grader looks for, then write the
# reference findings to /app/out/findings.json.
set -euo pipefail
mkdir -p /app/out
python3 - <<'PY'
import json, subprocess, sys
sys.path.insert(0, "/solution")
import reference_probe as rp
codes = {}
for verb, database, sql in rp.plan():
    run = subprocess.run(["tarn-cli", verb, "--db", "-", "--sql", sql],
                         input=json.dumps(database), capture_output=True, text=True)
    if run.returncode == 3:
        sys.exit(f"tarnd unreachable: {run.stderr.strip()}")
    if "TARN-400" in run.stderr:
        sys.exit(f"the service refused a reference database: {run.stderr.strip()}")
    codes[run.returncode] = codes.get(run.returncode, 0) + 1
print(f"replayed {sum(codes.values())} calls through tarn-cli; exit codes {codes}")
with open("/app/out/findings.json", "w", encoding="utf-8") as out:
    json.dump(rp.findings(), out, indent=2)
PY
tarn-cli budget
