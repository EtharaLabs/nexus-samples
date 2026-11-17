# microgrid-dispatch-outage

Dispatch a simulated island microgrid through a scheduled utility-tie outage over its EMS API for 72
grid hours, follow the utility operator's mid-run revisions of the supply contract, and report what in
the grid was not as it first seemed.

| Path | Contents |
| --- | --- |
| `instruction.md` | the request the agent receives |
| `task.toml` | runtime, timeouts, the allowlist network, the ems-sim collect step, and the artifact transfer of the incident report and the trial record |
| `environment/` | the agent image (the grid documents at `/app/plant`, a writable `/app/out`) and the compose file |
| `environment/ems-sim/` | the EMS sidecar, built only into its own image: the shared `plantops` server and collect step, the island microgrid simulator `plantsim`, and the pre-admitted seed pool |
| `tests/` | the verifier: `test.sh` (zero rule, one Reward Kit run), `grade.py` (reads the collect step's export and scores the incident report), `test_output.py` (5 compiled items), `judge.toml` (5 judged items, advisory), `reward.toml` (binary, all-pass; judge weight 0) |
| `solution/` | the reference dispatch policy `microgrid_ops`, `solve.sh`, and `TRUTH.md` |

Scoring is binary: the reward is the all-pass of the five compiled items O1-O5, where O1-O4 count
only when O5 is exactly 1.0. The judged items in `judge.toml` are advisory (weight 0) and never
change the reward. A trial passes only at exactly 1.0. A trial with no API call, no trial record,
or no incident report scores 0.0.
