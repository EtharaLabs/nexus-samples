#!/bin/bash
# Island microgrid verifier (Reward Kit 0.2.4). grade.py reads the ems-sim collect step's export
# (O1-O4 from its replay, and the expected incident set) and scores the incident report (O5); no
# simulator runs here. Reward is the binary all-pass of the compiled items O1-O5 (tests/reward.toml);
# the judged items in tests/judge.toml are advisory (weight 0) and never change the reward. A judge
# that cannot run, fails or times out is dropped and the compiled items are scored alone; that
# fallback refuses a judge that carries weight.
# FAIL-CLOSED: reward.txt starts at 0 and becomes 1 only when Reward Kit's reward is 1.0. Any grader
# or Reward Kit failure, a missing API call, or a missing incident report leaves it at 0, so every
# path writes the contract's /logs/verifier/reward.txt. rewardkit.json holds Reward Kit's own scores.
set -uo pipefail
logs=/logs/verifier
out=$logs/reward.txt
rk=$logs/rewardkit.json
mkdir -p "$logs"
rm -f "$out" "$logs/reward.json" "$rk" "$logs/reward-details.json" "$logs/grade.json"
echo 0 >"$out"

python3 /tests/grade.py >"$logs/grade.log" 2>&1 || exit 0

scratch=/tmp/rk
rm -rf "$scratch" && mkdir -p "$scratch"
cp /tests/test_output.py /tests/reward.toml /tests/judge.toml "$scratch/"
if ! REWARD_SCOPE=full timeout 1200 rewardkit "$scratch" --workspace /workspace --output "$rk" >"$logs/rewardkit.log" 2>&1; then
  python3 - /tests/reward.toml "$scratch/reward.toml" <<'PY' >>"$logs/rewardkit.log" 2>&1 || exit 0
import json
import pathlib
import sys
import tomllib

config = tomllib.loads(open(sys.argv[1]).read())
rewards = config.get("reward", [])
if not rewards or any(float(r.get("weights", {}).get("judge", 1.0)) != 0.0 for r in rewards):
    sys.exit("tests/reward.toml gives the judge weight, so its failure stands")
lines = []
for r in rewards:
    lines.append("[[reward]]")
    for key, value in r.items():
        if key == "weights":
            kept = ", ".join(f"{k} = {float(v)!r}" for k, v in value.items() if k != "judge")
            lines.append(f"weights = {{ {kept} }}")
        else:
            lines.append(f"{key} = {json.dumps(value)}")
    lines.append("")
for name, table in config.get("scoring", {}).items():
    lines.append(f"[scoring.{name}]")
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in table.items())
    lines.append("")
target = pathlib.Path(sys.argv[2])
target.unlink(missing_ok=True)
target.write_text("\n".join(lines))
PY
  rm -f "$scratch/judge.toml"
  echo "the judge did not complete; it carries no weight, so the compiled items are scored alone" >>"$logs/rewardkit.log"
  REWARD_SCOPE=full rewardkit "$scratch" --workspace /workspace --output "$rk" >>"$logs/rewardkit.log" 2>&1 || exit 0
fi
if python3 -c 'import json, sys; sys.exit(json.load(open(sys.argv[1]))["reward"] < 1.0 - 1e-9)' "$rk"; then
  echo 1 >"$out"
fi
exit 0
