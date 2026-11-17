#!/bin/bash
# Binary reward (task.toml reward_type = "binary", Reward Kit 0.2.4). grade.py re-runs
# every finding against the shipped engine, the reference and the seven single-fix
# variants and writes the twelve compiled items tests/test_output.py reads: the seven
# defects, minimality in rows, schema and statement, reproduction and boundary. When
# all twelve pass, Reward Kit also runs the judged criteria of tests/judge.toml, and
# tests/reward.toml weights the compiled items 1 and the judge 0, so the judge's verdicts
# are reported and never change the reward. A judge that cannot run, fails or times out
# is dropped and the compiled items are scored alone; that fallback refuses a judge that
# carries weight. reward.txt is 0 from the start and becomes 1 only when Reward Kit's
# reward is 1.0, so every path ends with a reward: a grader or Reward Kit fault scores 0.
# Where the sandbox lets root switch users, the judge runs as uid 1000 (tests/codex-judge.sh):
# it reads the files below but cannot write /logs/verifier, /tests or /workspace, and root
# settles the reward last.
set -uo pipefail
logs=/logs/verifier
out=$logs/reward.txt
rk=$logs/rewardkit.json
judge=/workspace/judge
mkdir -p "$logs" "$judge"
chown root:root "$logs" 2>/dev/null
chmod 0755 "$logs"
rm -f "$out" "$rk" "$logs/reward.json" "$logs/reward-details.json" "$logs/grade.json"
echo 0 >"$out"

stop_judge() {
  python3 - <<'PY'
import os
import signal
import time

for _ in range(50):
    pids = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/status") as fh:
                fields = dict(line.rstrip("\n").split(":\t", 1) for line in fh if ":\t" in line)
        except OSError:
            continue
        if not fields.get("State", "").startswith("Z") and "1000" in fields.get("Uid", "").split():
            pids.append(int(name))
    if not pids:
        break
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.1)
PY
}

fault() {
  echo "VERIFIER FAULT: $1; the reward stays 0"
  stop_judge
  rm -f "$logs/reward.json"
  echo 0 >"$out"
  exit 0
}

FINDINGS=/app/out/findings.json
LOG=/results/calls.jsonl
if [ ! -f "$FINDINGS" ]; then
  echo "no findings.json was written"
  printf '{"items":{},"compiled":0.0,"gate":{"ok":false,"false_claims":["no findings.json was written"]}}\n' \
    >"$logs/grade.json"
  exit 0
fi
[ -f "$LOG" ] || LOG=/dev/null

cp "$FINDINGS" "$judge/findings.json"
cp "$LOG" "$judge/calls.jsonl"
cp /tests/DESIGN.md "$judge/DESIGN.md"
chmod 0755 /workspace "$judge"
chmod 0644 "$judge/findings.json" "$judge/calls.jsonl" "$judge/DESIGN.md"

python3 /tests/grade.py --findings "$FINDINGS" --build /build --log "$LOG" \
  --budget "${TARND_BUDGET:-250}" --out "$logs/grade.json" >"$logs/grade.log" 2>&1 \
  || { cat "$logs/grade.log"; fault "grade.py failed"; }
cat "$logs/grade.log"
chmod 0644 "$logs/grade.json"

if ! python3 -c 'import json, sys; r = json.load(open(sys.argv[1])); sys.exit(not (r["gate"]["ok"] and r["items"] and all(v >= 1.0 for v in r["items"].values())))' "$logs/grade.json"; then
  echo "reward: 0 (a compiled item failed, so the judge is not consulted)"
  exit 0
fi

scratch=/tmp/rk
rm -rf "$scratch" && mkdir -p "$scratch"
cp /tests/test_output.py /tests/reward.toml /tests/judge.toml "$scratch/"
timeout 1500 rewardkit "$scratch" --workspace /workspace --output "$rk" >"$logs/rewardkit.log" 2>&1
status=$?
stop_judge
if [ "$status" -ne 0 ]; then
  tail -40 "$logs/rewardkit.log"
  python3 - /tests/reward.toml "$scratch/reward.toml" <<'PY' || fault "Reward Kit failed (exit $status) and the judge carries weight"
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
  echo "the judge did not complete (exit $status); it carries no weight, so the compiled items are scored alone"
  rewardkit "$scratch" --workspace /workspace --output "$rk" >>"$logs/rewardkit.log" 2>&1 \
    || { tail -40 "$logs/rewardkit.log"; fault "Reward Kit failed"; }
fi
python3 - "$rk" <<'PY'
import json
import pathlib
import sys

body = json.loads(pathlib.Path(sys.argv[1]).read_text())
print("reward kit:", json.dumps({k: v for k, v in body.items() if not isinstance(v, (dict, list))}))
details = pathlib.Path("/logs/verifier/reward-details.json")
if details.exists():
    try:
        for name, rec in json.loads(details.read_text()).items():
            print(f"  {name}: {json.dumps(rec)[:400]}")
    except Exception:
        pass
PY
rm -f "$logs/reward.json"
if python3 -c 'import json, sys; sys.exit(json.load(open(sys.argv[1]))["reward"] < 1.0 - 1e-9)' "$rk"; then
  echo 1 >"$out"
else
  echo 0 >"$out"
fi
echo "reward: $(cat "$out")"
exit 0
