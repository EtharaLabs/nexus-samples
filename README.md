<p align="center">
  <img src="images/hero.svg" alt="nexus: hard, measurable agent tasks graded on a continuous score" width="880">
</p>

<p align="center">
  <strong>Hard, measurable engineering tasks for LLM agents, graded on a continuous score.</strong>
</p>

<p align="center">
  <a href="#summary"><img alt="Built by Ethara.AI" src="https://img.shields.io/badge/built%20by-Ethara.AI-ee00ee.svg"></a>
  <a href="#what-every-task-is"><img alt="Scoring: continuous, partial credit" src="https://img.shields.io/badge/scoring-continuous_·_partial_credit-35d0ba.svg"></a>
  <a href="#what-every-task-is"><img alt="Verifier: isolated" src="https://img.shields.io/badge/verifier-isolated_container-845EF7.svg"></a>
  <a href="#summary"><img alt="Hardware: CPU-only" src="https://img.shields.io/badge/hardware-CPU--only_(amd64_·_arm64)-ff6b6b.svg"></a>
  <a href="#license"><img alt="License: see LICENSE" src="https://img.shields.io/badge/license-see_LICENSE-64748b.svg"></a>
</p>

<p align="center">
  <a href="#summary">Summary</a> · <a href="#what-every-task-is">Task anatomy</a> · <a href="#repository-layout">Layout</a> · <a href="#task-catalog">Task catalog</a> · <a href="#recorded-runs">Recorded runs</a> · <a href="#verification-and-quality-assurance">Verification</a> · <a href="#license">License</a>
</p>

This is the **samples lane** of the nexus corpus: hard, verifiable engineering tasks that hand an LLM agent a precise spec, a deliberately weak or stub baseline, and a sealed sandbox, then grade the delivered artifact on a **continuous score** against a hidden reference. The two resident bundles are a hardware task (graph-based static timing analysis) and a software task (an exactly-once streaming engine) - both correctness-dense problems where a single wrong inequality or missed edge case is exposed only by the verifier.

Each bundle ships the frozen task beside its authoring-side oracle and **recorded model runs** - the full agent trajectories and the verifier's per-criterion reward breakdown.

> **Any bundle that ships an oracle (`solution/TRUTH.md`) or recorded runs cannot be used to *blind-evaluate* a model that has seen it** - withhold `solution/` and `tests/` first. The dataset format, task format, and scoring here are identical to the production benchmark.

## Summary

| Property | Value |
| :------- | :---- |
| Bundles | **2** (NLDM Static Timing Analysis · Exactly-once Session-Window Streaming) |
| Score | a continuous value in `[0, 1]` (partial credit), never binary; a run passes only at exactly `1.0` |
| Reward schema | `weighted-mean(test_output = 9, judge = 1)` - 90% compiled checks, 10% LLM-judged review; a non-compiling deliverable floors to `0.0` |
| Hardware | CPU-only by design (2 vCPU / 2 GB), built for `linux/amd64` and `linux/arm64` |
| Network | agent phase `no-network`; the verifier is allow-listed to the judge endpoint (`chatgpt.com`, `auth.openai.com`) only |
| Grading | isolated verifier container (`environment_mode = "separate"`), run as a distinct user; the agent cannot access or modify it |
| Recorded runs | both bundles ship a `claude-opus-5` (claude-code) run under `trajectories/`, with config, logs, the submitted artifact, and the verifier's `reward.json` / `reward-details.json` |
| Format | frozen task (`instruction.md` · `task.toml` · `environment/` · `solution/` · `tests/`) per uuid-named directory, plus the recorded-run bundle |
| Audit | both bundles carry a CRUCIBLE verdict in [`VERDICT.md`](VERDICT.md) |

### What every task is

| Property | Description |
| :------- | :---------- |
| **Precise objective** | `instruction.md` states the exact contract - every rule, schema key, and tolerance - and keeps the implementation open. The agent delivers one self-contained program using only the language standard library. |
| **Weak / stub baseline** | A deliberately incomplete starter ships in the environment (the streaming task's `/app/stream` only ACKs events and writes EOF; the STA task ships only parsing samples with no reference reports). Building the correct engine is the task. |
| **Continuous score** | The score is a **float on `[0, 1]`, higher is better**, never binary. It is `0.9 ×` the weighted mean of the compiled checks on fresh hidden cases plus `0.1 ×` the weighted mean of the judged source reviews. A run passes only when the reward is exactly `1.0`. |
| **Hidden evaluation** | Cases are drawn fresh from a per-run seed, never shipped to the agent. The STA grader redraws its hidden libraries/netlists/constraints each run; the streaming grader generates seeded traces and compares the agent subprocess byte-for-byte against an embedded reference, clean and across crash/resume. |
| **Isolated verifier** | Grading runs in a separate image from the agent, as a non-root grader user, with the hidden graders, reference, and generators baked in - the agent never sees `solution/` or `tests/`. |

## Repository layout

Every task ships the same shape: the five frozen-task entries at the top level, plus a recorded-run bundle beside them.

```
nexus-samples/
├── README.md                     ← this file
├── VERDICT.md                    ← CRUCIBLE audit of the two resident bundles
├── images/                       ← README assets (hero.svg)
│
└── <uuid>/                       ← one bundle per task (2 resident)
    ├── instruction.md            ← agent-facing spec: objective, rules, scoring, constraints
    ├── task.toml                 ← Harbor descriptor: env / agent / verifier / score schema
    ├── environment/              ← Dockerfile + starter/stub code + parsing samples or config
    ├── solution/                 ← oracle: TRUTH.md + grounding/policy/provenance; reference(s), solve.sh
    ├── tests/                    ← verifier harness: test.sh, reward.toml, judge.toml, test_output.py, hidden generators
    ├── README.md                 ← per-task write-up (where shipped)
    └── trajectories/             ← recorded runs, one subtree per model cohort: config, logs, submission, reward
```

### The common per-task files

| Path | Role |
| :--- | :--- |
| `instruction.md` | The problem statement delivered to the agent: objective, the full rule set, the exact output schema and tolerance, and the exit-status contract. |
| `task.toml` | Machine-readable task descriptor: docker image (pinned by digest), CPU/memory, network mode, agent timeout, verifier config, reward schema, and provenance. |
| `environment/` | What the agent starts from: a `Dockerfile`, the weak/stub baseline, and any parsing samples or config (the samples are never graded). |
| `solution/` | The authoring-side oracle. Every bundle ships **`TRUTH.md`** (the golden trajectory, rubric, and the explicitly rejected score-hacking routes), plus `grounding.yaml`, `policy.yaml`, `provenance.yaml`; the streaming bundle adds `reference.py` and an independent `reference_alt.py`, the STA bundle adds the oracle `sta.py`. |
| `tests/` | The verifier. Every bundle ships `test.sh`, `reward.toml`, `judge.toml`, and `test_output.py` (compiled criteria); the STA bundle adds the hidden `gen_design.py` and `sta_ref.py`, and each ships its own verifier `Dockerfile`. |
| `trajectories/` | The recorded model runs, one subtree per model cohort: run config and logs, the agent transcript, the submitted artifact, and the verifier's `reward.json` / `reward-details.json`. |

> The judged carrier is a list of *standalone, atomic, natural-language* checks scored by an LLM judge (`codex`) against the delivered source - it is ≤ 10% of the reward and never gates a passing compiled run.

## Task catalog

Two tasks span a hardware/EDA correctness problem and a stateful-systems problem.

| # | UUID (dir) | Domain | Objective |
| :-- | :--------- | :----- | :-------- |
| 1 | `136de480-2df4-5b30-8686-685cbc5749d7` | Hardware · static timing analysis | Build a **graph-based static timing analyser** over Liberty NLDM, structural Verilog, and SDC 2.1: propagated clocks with CPPR, generated and multiple clocks, setup and hold, multicycle and false paths, latch time borrowing, and OCV derates - a stdlib-only Python program graded to `1e-6` ns against a hidden reference, each case within 20 s. |
| 2 | `8263dbf4-358b-52b2-8ff0-2b26ffcafa67` | Software · stateful streaming | Implement a **single-threaded deterministic session-window streaming engine** with watermark-driven finalization, late-event retraction and re-finalization, and **bit-identical exactly-once** output across a crash/resume boundary - compared byte-for-byte against an embedded reference, clean and across chunked restarts. |

## Recorded runs

Both tasks ship a recorded model run under `trajectories/`, with the raw submission and the deterministic verifier's reward breakdown. Scores are on the continuous `[0, 1]` scale.

| Task | Model cohort (agent) | Runs recorded | Best score | Breakdown |
| :--- | :------------------- | :------------ | :--------- | :-------- |
| NLDM Static Timing Analysis | `claude-opus-5` (claude-code) | 1 | **0.7845** | compiled `0.7606` (×0.9) · judge `1.0000` (×0.1); run hit the agent timeout before converging |
| Exactly-once Session-Window Streaming | `claude-opus-5` (claude-code) | 1 | **0.5900** | compiled `0.5641` (×0.9) · judge `0.8235` (×0.1); judge flagged the late-bridge re-FINAL and the canonical emit order |

Neither recorded run reaches `1.0`; the oracle-pass feasibility and the open items are documented per bundle and audited in [`VERDICT.md`](VERDICT.md). Read it before quoting any of these numbers.

## Verification and quality assurance

Grading is a single Reward Kit stage in an isolated verifier image: the compiled criteria in `tests/test_output.py` (weighted `test_output = 9`) plus the judged criteria in `tests/judge.toml` (weighted `judge = 1`), combined by the weights in `tests/reward.toml`. A deliverable that is absent, empty, or does not byte-compile scores `0.0` with no grader or judge run. The streaming bundle additionally ships an independent second reference (`reference_alt.py`) that is byte-identical to the primary reference across seeds and crash/resume, so the graded output is proven to be determined by the spec rather than one implementation.

## Reproduction

Each bundle directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image, and `tests/` the verifier. Point a Harbor runner at one bundle directory to reproduce it; `solution/` stays private.

## License

See [LICENSE](LICENSE) for the terms under which this repository is published.

## Contact

[Ethara AI on GitHub](https://github.com/Ethara-Ai), [SECURITY.md](SECURITY.md) for a private report, and [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution route.

---

## Copyright

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
