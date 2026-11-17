#!/bin/bash
# FORGE-CANARY-BEGIN
# FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-END
# Oracle: run the expert reference policy (solution/coldsnap_ops) against the live SCADA API for
# the whole 72 plant hours, then write its incident report. It uses only the documented API and
# the shipped documents; it reads no byte of environment/scada-sim/.
set -euo pipefail
export PYTHONPATH="/solution${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1
mkdir -p /app/out
python3 - <<'PY'
import json
from pathlib import Path

from coldsnap_ops.clients import HttpClient
from coldsnap_ops.operator import Operator

result = Operator(HttpClient("http://scada-sim:8080"), "reference").run()
out = Path("/app/out/6c55cb9f-e734-5025-8e5f-43ef2f4336fa_D2_incidents.json")
tmp = out.with_suffix(".tmp")
tmp.write_text(json.dumps(result["incidents"], indent=1) + "\n")
tmp.replace(out)
print("\n".join(result["log"]))
PY
