#!/bin/bash
# Binary reward (task.toml reward_type = "binary", Reward Kit 0.2.4). grade.py re-runs
# every finding against the reference, the shipped engine and the twelve single-fix
# variants, stages the judge's inputs, and writes the twenty compiled items
# tests/test_output.py reads. When all twenty pass with the precision gate clear,
# Reward Kit also runs the judged criteria of tests/judge.toml, and tests/reward.toml
# weights the compiled items 1 and the judge 0, so the judge's verdicts are reported and
# never change the reward. A judge that cannot run, fails or times out is dropped and the
# compiled items are scored alone; that fallback refuses a judge that carries weight.
# reward.txt starts at 0 and becomes 1 only when Reward Kit's reward is 1.0, so every
# path ends with a reward: a grader or Reward Kit fault leaves it at 0.
#
# The grader's own files are found beside this script, and the judge's inputs are staged
# in judge/ under the working directory. Three locations are Harbor's: the directory it
# reads the reward from, and the two places it puts the artifacts task.toml collects.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
logs=/logs/verifier
out=$logs/reward.txt
rk=$logs/rewardkit.json
judge=judge
mkdir -p "$logs" "$judge"
rm -f "$out" "$rk" "$logs/reward.json" "$logs/reward-details.json" "$logs/grade.json"
echo 0 >"$out"

fault() {
  echo "VERIFIER FAULT: $1; the reward stays 0"
  rm -f "$logs/reward.json"
  echo 0 >"$out"
  exit 0
}

FINDINGS=/app/out/findings.json
LOG=/srv/results/calls.jsonl
[ -f "$FINDINGS" ] || echo "no findings.json was written"
[ -f "$LOG" ] || LOG=""

python3 "$here/grade.py" --findings "$FINDINGS" --build "$here/build" --log "$LOG" \
  --budget "${WARDD_BUDGET:-240}" --judge-dir "$judge" \
  --out "$logs/grade.json" >"$logs/grade.log" 2>&1 \
  || { cat "$logs/grade.log"; fault "grade.py failed"; }
cat "$logs/grade.log"
[ -f "$logs/grade.json" ] || fault "grade.py wrote no grade.json"

python3 - "$logs/grade.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
for name, score in report.get("items", {}).items():
    print(f"  {name:30s} {score:.0f}")
for rec in report.get("findings", []):
    notes = [f"{k}={rec[k]}" for k in ("verdict", "expected_ok", "observed_ok") if k in rec]
    print(f"  finding {rec.get('index')}: " + " ".join(str(n) for n in notes))
PY

if ! python3 -c 'import json, sys; r = json.load(open(sys.argv[1])); i = r.get("items", {}); sys.exit(not (r.get("gate", {}).get("ok") and len(i) == 20 and all(v >= 1.0 for v in i.values())))' "$logs/grade.json"; then
  echo "reward: 0 (a compiled item failed, so the judge is not consulted)"
  exit 0
fi

# Reward Kit reads the compiled items from grade.json beside test_output.py.
stage="$(mktemp -d)"
cp "$here/test_output.py" "$here/reward.toml" "$here/judge.toml" "$logs/grade.json" "$stage/"
if ! REWARD_SCOPE=full timeout 1500 rewardkit "$stage" --workspace . --output "$rk" >"$logs/rewardkit.log" 2>&1; then
  tail -40 "$logs/rewardkit.log"
  python3 - "$here/reward.toml" "$stage/reward.toml" <<'PY' || fault "Reward Kit failed and the judge carries weight"
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
  rm -f "$stage/judge.toml"
  echo "the judge did not complete; it carries no weight, so the compiled items are scored alone"
  REWARD_SCOPE=full rewardkit "$stage" --workspace . --output "$rk" >>"$logs/rewardkit.log" 2>&1 \
    || { tail -40 "$logs/rewardkit.log"; fault "Reward Kit failed"; }
fi
python3 - "$rk" "$logs/reward-details.json" <<'PY'
import json
import pathlib
import sys

body = json.loads(pathlib.Path(sys.argv[1]).read_text())
print("reward kit:", json.dumps({k: v for k, v in body.items() if not isinstance(v, (dict, list))}))
details = pathlib.Path(sys.argv[2])
if details.exists():
    try:
        for name, rec in json.loads(details.read_text()).items():
            print(f"  {name}: {json.dumps(rec)[:400]}")
    except Exception:
        pass
PY
if python3 -c 'import json, sys; sys.exit(json.load(open(sys.argv[1]))["reward"] < 1.0 - 1e-9)' "$rk"; then
  echo 1 >"$out"
fi
echo "reward: $(cat "$out")"
exit 0
