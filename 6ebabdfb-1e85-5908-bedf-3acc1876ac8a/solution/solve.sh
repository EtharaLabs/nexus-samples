#!/bin/bash
# Oracle: replay the reference investigation through ward-cli, which proves the service
# path and the call log end to end, then write the findings. It runs as the agent's
# user in the agent's working directory (the one holding docs/ and sample/), finds its
# own files beside this script, and writes only out/findings.json and temporary files;
# findings.json beside this script is the output of reference_probe.py, shipped as it is.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p out
python3 - "$here" <<'PY'
import json, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[1])
import reference_probe as rp
codes = {}
calls = rp.plan()
for verb, world, query in calls:
    wf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(world, wf); wf.close()
    r = subprocess.run(["ward-cli", verb, "--world", wf.name, "--query", json.dumps(query)],
                       capture_output=True, text=True)
    if r.returncode == 3:
        sys.exit("the decision service is unreachable: " + r.stderr.strip())
    if "WARD-400" in r.stdout + r.stderr:
        sys.exit("the service refused a reference call as invalid: " + (r.stdout + r.stderr).strip())
    codes[r.returncode] = codes.get(r.returncode, 0) + 1
print(f"replayed {len(calls)} calls through ward-cli; exit codes {codes}")
PY
cp "$here/findings.json" out/findings.json
ward-cli budget
