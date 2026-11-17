#!/bin/bash
# FORGE-CANARY-BEGIN
# FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-END
# Oracle: run the expert reference policy (solution/microgrid_ops) against the live EMS API for
# the whole 72 grid hours, then write its incident report. It uses only the documented API and
# the shipped documents; it reads no byte of environment/ems-sim/.
set -euo pipefail
export PYTHONPATH="/solution${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1
mkdir -p /app/out
python3 - <<'PY'
import json
from pathlib import Path

from microgrid_ops.clients import HttpClient
from microgrid_ops.operator import Operator

result = Operator(HttpClient("http://ems-sim:8080"), "reference").run()
out = Path("/app/out/249cfe22-173e-5a63-a907-25c23196b668_D2_incidents.json")
tmp = out.with_suffix(".tmp")
tmp.write_text(json.dumps(result["incidents"], indent=1) + "\n")
tmp.replace(out)
print("\n".join(result["log"]))
PY
