#!/bin/bash
# Single-stage continuous reward (Reward Kit 0.2.4): the weighted mean of every compiled item in
# tests/test_output.py and every judged item in tests/judge.toml, weighted by tests/reward.toml.
# A D1 that is absent, empty, or does not byte-compile scores 0.0 inline: no Reward Kit, no judge.
# A Reward Kit failure leaves no reward file, so it is a verifier error and never a pass.
set -uo pipefail
logs=/logs/verifier
out=/logs/verifier/reward.json
d1=/app/out/136de480-2df4-5b30-8686-685cbc5749d7_D1_sta.py
mkdir -p "$logs"
rm -f "$out" "$logs/reward-details.json"

if ! python3 - "$d1" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1])
try:
    source = target.read_bytes() if target.is_file() else b""
    compile(source, str(target), "exec")
except (OSError, SyntaxError, ValueError):
    sys.exit(1)
sys.exit(0 if source.strip() else 1)
PY
then
  printf '%s\n' '{"reward": 0.0, "test_output": 0.0, "judge": 0.0}' >"$out"
  exit 0
fi

REWARD_SEED="$(python3 -c 'import secrets; print(secrets.randbits(48))')"
export REWARD_SEED
scratch=/tmp/rk
rm -rf "$scratch" && mkdir -p "$scratch"
cp /tests/test_output.py /tests/reward.toml "$scratch/"
cp /tests/judge.toml "$scratch/judge.toml"
REWARD_SCOPE=full rewardkit "$scratch" --workspace /app --output "$out" >"$logs/rewardkit.log" 2>&1
status=$?
if [ "$status" -ne 0 ]; then
  rm -f "$out"
  exit "$status"
fi
exit 0
