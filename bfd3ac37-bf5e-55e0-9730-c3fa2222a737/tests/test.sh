#!/bin/bash
# Binary reward (Reward Kit 0.2.4). tests/reward.toml weights the compiled items O1-O5 of
# tests/test_output.py 1 and the judged items of tests/judge.toml 0, so the reward is 1 only
# when every compiled item passes, and 0 otherwise; the judge's verdicts are reported and never
# change it. A judge that cannot run, fails or times out is dropped and the compiled items are
# scored alone; that fallback refuses a judge that carries weight.
# grade.py reads the scada-sim collect step's export (O1-O4 from its replay, the expected
# incident set, and the judge's request and action logs) and scores the incident report (O5); no
# simulator runs here.
# The reward goes to reward.txt and starts at 0 (fail-closed): the zero rule (no API call recorded,
# or no incident report), a grade.py failure, a Reward Kit failure, or a score below 1.0 leaves 0.
# Reward Kit's reward goes to rewardkit.json; its reward-details.json stays in /logs/verifier.
# On every exit, the zero path included, grade.py writes the CTRF report of the cheat checks that
# tests/cheat-checks.json declares to /logs/verifier/ctrf.json; it never writes a reward.
set -uo pipefail
logs=/logs/verifier
out=$logs/reward.txt
rk=$logs/rewardkit.json
mkdir -p "$logs"
rm -f "$out" "$logs/reward.json" "$rk" "$logs/reward-details.json" "$logs/grade.json" "$logs/ctrf.json"
trap 'python3 /tests/grade.py ctrf >>"$logs/grade.log" 2>&1' EXIT
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
# The tolerance only absorbs float rounding.
if python3 -c 'import json, sys; sys.exit(json.load(open(sys.argv[1]))["reward"] < 1.0 - 1e-9)' "$rk"; then
  echo 1 >"$out"
fi
exit 0
