#!/bin/bash
# Binary reward (Reward Kit 0.2.3), fail-closed. reward.txt starts at 0 and becomes 1 only
# when Reward Kit completes with a reward of 1.0. tests/reward.toml weights the compiled
# criteria 1 and the judge 0, so the judge's verdicts are reported and never change the
# reward. A judge that cannot run, fails or times out is dropped and the compiled criteria
# are scored alone; that fallback refuses a judge that carries weight. Any other Reward Kit
# fault or a score below 1.0 leaves the reward at 0, so every path writes a reward to the
# contract's /logs/verifier/reward.txt. Reward Kit's own /logs/verifier/reward.json is read
# to derive the binary reward and then removed, so only reward.txt remains.
set -uo pipefail
logs=/logs/verifier
out=$logs/reward.txt
mkdir -p "$logs"
rm -f "$out" "$logs/reward.json" "$logs/reward-details.json"
echo 0 >"$out"

if ! timeout 1200 rewardkit /tests >"$logs/rewardkit.log" 2>&1; then
  tail -40 "$logs/rewardkit.log"
  scratch=/tmp/rk
  rm -rf "$scratch" && mkdir -p "$scratch"
  cp /tests/test_output.py "$scratch/"
  python3 - /tests/reward.toml "$scratch/reward.toml" <<'PY' >>"$logs/rewardkit.log" 2>&1 || { echo "Reward Kit failed and the judge carries weight; the reward stays 0"; exit 0; }
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
  echo "the judge did not complete; it carries no weight, so the compiled criteria are scored alone" | tee -a "$logs/rewardkit.log"
  rm -f "$logs/reward.json" "$logs/reward-details.json"
  if ! rewardkit "$scratch" >>"$logs/rewardkit.log" 2>&1; then
    tail -40 "$logs/rewardkit.log"
    echo "Reward Kit failed; the reward stays 0"
    exit 0
  fi
fi

if [ -f "$logs/reward.json" ] && \
   python3 -c 'import json, sys; sys.exit(json.load(open("/logs/verifier/reward.json"))["reward"] < 1.0 - 1e-9)'; then
  echo 1 >"$out"
fi
rm -f "$logs/reward.json"
echo "reward: $(cat "$out")"
exit 0
