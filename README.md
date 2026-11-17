<p align="center"><img src="images/hero.svg" alt="nexus" width="720"></p>

# Nexus TerminalBench 4.0: samples

<p align="center"><b>Five sample tasks from nexus, a corpus of hard, realistic command-line work for evaluating autonomous agents.</b></p>

<p align="center"><a href="#summary"><img src="https://img.shields.io/badge/samples-5%2F5-845EF7" alt="samples: 5/5"></a> <a href="#summary"><img src="https://img.shields.io/badge/harbor_schema-1.4-845EF7" alt="harbor schema: 1.4"></a> <a href="#trials"><img src="https://img.shields.io/badge/difficulty-unsolved_by_frontier-845EF7" alt="difficulty: unsolved by frontier"></a></p>

<p align="center"><sub><a href="#abstract">Abstract</a> | <a href="#summary">Summary</a> | <a href="#tasks">Tasks</a> | <a href="#trials">Trials</a> | <a href="#coverage">Coverage</a> | <a href="#dataset-structure">Dataset structure</a> | <a href="#reproduction">Reproduction</a> | <a href="#cite">Cite</a> | <a href="#contact">Contact</a></sub></p>

## Abstract

Nexus is a corpus of hard, realistic evaluation tasks in [Harbor](https://github.com/laude-institute/harbor) format, drawn from command-line, software, and operations work. This is based on TerminalBench 4.0. Every task ships a sandbox image, the instruction the agent reads, a verifier hidden from the agent, and a reference solution. The reward is binary: a rollout scores 1 only when every compiled criterion passes.

This repository holds the five-task sample. Two tasks are black-box diagnoses: the agent finds the defects in an access-policy engine or a relational engine that it can reach only as a budgeted network service, and reports each one against the specification rule it breaks. One task builds a deterministic session-window streaming engine whose output must stay exactly-once across a crash and resume. Two tasks are long-horizon operations: the agent runs a simulated district-heating plant or an island microgrid through its API for 72 simulated hours and reports every incident the system hid.

Each sample ships one rollout by Claude Code with `claude-opus-5-5`, scored by the task's own verifier. None of the five trials reached reward 1, while the best passed 11 of 12 compiled criteria, so every task keeps headroom above `claude-opus-5-5`.

## Summary

| Property | Value |
| --- | --- |
| Samples | 5/5 |
| Target Benchmark | TerminalBench 4.0 |
| Domains | Operations (grid operations, plant operations); software (authorization, databases, stateful streaming) |
| Format | Harbor task, schema 1.4 |
| Platforms | linux/amd64, linux/arm64 |
| Base image | `python:3.13-slim-bookworm`, digest-pinned |
| Reward | Binary, from the compiled tests; LLM-judged criteria are recorded at weight 0 |
| Agent time limit | 1 to 8 hours per task |
| Agent | Claude Code 2.1.310 and 2.1.326 with `claude-opus-5-5` |
| Trials | 1 per task |
| Solved by `claude-opus-5-5` | 0 of 5 |
| Compiled criteria passed | 24 of 59 |
| Mean cost per rollout | 3.11 USD |
| Mean agent time | 1h 54m 28s |

## Tasks

| Task | Category | Area | Objective | Time limit |
| --- | --- | --- | --- | --- |
| [`249cfe22`](249cfe22-173e-5a63-a907-25c23196b668/) | Operations | Grid operations | Dispatch a simulated island microgrid through a scheduled utility-tie outage over its API for 72 grid hours, follow the utility operator's mid-run revisions, and report every incident the grid hid. | 8 h |
| [`6ebabdfb`](6ebabdfb-1e85-5908-bedf-3acc1876ac8a/) | Software | Authorization | Diagnose twelve defects in an access-policy decision engine reachable only as a budgeted network service, and report each as a minimal, reproduced and bounded finding citing the specification rule it breaks. | 1 h |
| [`8263dbf4`](8263dbf4-358b-52b2-8ff0-2b26ffcafa67/) | Software | Stateful streaming | Implement a single-threaded deterministic session-window streaming engine with watermark-driven finalization, late-event retraction and re-finalization, and bit-identical exactly-once output across a crash/resume boundary. | 1 h |
| [`bfd3ac37`](bfd3ac37-bf5e-55e0-9730-c3fa2222a737/) | Operations | Plant operations | Operate a simulated district-heating plant through its SCADA API for 72 plant hours so that a cold snap passes without breaking the customer contract, and report every incident the plant hid. | 4 h |
| [`c6be7353`](c6be7353-782a-54cf-b9f3-283f13558982/) | Software | Databases | Diagnose seven defects in a relational engine reachable only as a network service, under a budget of 250 queries, and report each one with the specification section it breaks, the observable it shows in, and a minimal statement and database that demonstrate it, each reproduced and bounded in the service's call log. | 1 h |

## Trials

Each task was run once by Claude Code with `claude-opus-5-5`, under the task's own time limit, and scored by the task's own verifier. Trials are stored in each task's `trials/opus-5-5/<trial>/`.

| Task | Reward | Compiled criteria passed | Cost (USD) | Agent time |
| --- | ---: | ---: | ---: | ---: |
| [`249cfe22-173e-5a63-a907-25c23196b668`](249cfe22-173e-5a63-a907-25c23196b668/trials/opus-5-5/) | 0 | 0 / 5 | 5.25 | 6h 1m 43s |
| [`6ebabdfb-1e85-5908-bedf-3acc1876ac8a`](6ebabdfb-1e85-5908-bedf-3acc1876ac8a/trials/opus-5-5/) | 0 | 0 / 20 | 0.98 | 5m 22s |
| [`8263dbf4-358b-52b2-8ff0-2b26ffcafa67`](8263dbf4-358b-52b2-8ff0-2b26ffcafa67/trials/opus-5-5/) | 0 | 9 / 17 | 0.27 | 1m 29s |
| [`bfd3ac37-bf5e-55e0-9730-c3fa2222a737`](bfd3ac37-bf5e-55e0-9730-c3fa2222a737/trials/opus-5-5/) | 0 | 4 / 5 | 4.53 | 3h 2m 29s |
| [`c6be7353-782a-54cf-b9f3-283f13558982`](c6be7353-782a-54cf-b9f3-283f13558982/trials/opus-5-5/) | 0 | 11 / 12 | 4.53 | 21m 18s |
| **mean** | **0.00** | **24 / 59** | **3.11** | **1h 54m 28s** |

The **mean** row averages reward, cost, and agent time over the five trials; its criteria cell is the total across them. A rollout scores 1 only when every compiled criterion passes (the two diagnosis tasks also need a clear precision gate), so the criteria column shows how close each rollout came. Each verifier also records LLM-judged criteria at weight 0, which do not change the reward.

Two rows read 0 because a gate zeroes their items rather than for lack of progress. `249cfe22` met all four plant outcomes (O1 to O4) in its replay and 7 of its 8 reported incidents matched, but the task counts the plant outcomes only with a complete incident report. `6ebabdfb` had 10 of its 12 findings credited, but two entries showed no difference, and its precision gate scores every item 0 when any claim is false.

Each trial folder is Harbor's trial output:

| Path | Contents |
| --- | --- |
| `config.json`, `lock.json` | Trial configuration and resolved run settings |
| `result.json` | Agent, model, token usage, cost, timings, and verifier reward |
| `job.log` | Harbor's log of the trial |
| `agent/` | Agent trajectory (`trajectory.json`), Claude Code session transcript (`sessions/`), and agent output (`claude-code.txt`) |
| `verifier/` | `reward.txt`, test output (`test-stdout.txt`), and grading details (`grade.json` or `reward-details.json`) |
| `artifacts/` | Files the agent produced, collected from the paths declared in `task.toml`, with a `manifest.json` |

The job folder `trials/opus-5-5/` also holds the job's `config.json`, `lock.json`, `result.json`, and `job.log`.

## Coverage

| Keyword | Tasks |
| --- | --- |
| access-policy | 1 |
| authorization | 1 |
| battery-storage | 1 |
| black-box-diagnosis | 2 |
| condensing-boilers | 1 |
| control | 1 |
| crash-recovery | 1 |
| dispatch | 1 |
| district-heating | 1 |
| ems | 1 |
| exactly-once | 1 |
| experiment-design | 2 |
| island-mode | 1 |
| microgrid | 1 |
| npsh | 1 |
| observation-budget | 2 |
| operations | 2 |
| python | 3 |
| query-optimizer | 1 |
| retraction | 1 |
| scada | 1 |
| sensor-faults | 2 |
| session-window | 1 |
| sql | 1 |
| steerability | 1 |
| streaming | 1 |
| thermal-storage | 1 |
| watermark | 1 |

## Dataset structure

Each task is one Harbor task in a directory named by its uuid.

| Task | Keywords |
| --- | --- |
| [`249cfe22-173e-5a63-a907-25c23196b668`](249cfe22-173e-5a63-a907-25c23196b668/) | battery-storage, dispatch, ems, island-mode, microgrid, operations, sensor-faults, steerability |
| [`6ebabdfb-1e85-5908-bedf-3acc1876ac8a`](6ebabdfb-1e85-5908-bedf-3acc1876ac8a/) | access-policy, authorization, black-box-diagnosis, experiment-design, observation-budget, python |
| [`8263dbf4-358b-52b2-8ff0-2b26ffcafa67`](8263dbf4-358b-52b2-8ff0-2b26ffcafa67/) | crash-recovery, exactly-once, python, retraction, session-window, streaming, watermark |
| [`bfd3ac37-bf5e-55e0-9730-c3fa2222a737`](bfd3ac37-bf5e-55e0-9730-c3fa2222a737/) | condensing-boilers, control, district-heating, npsh, operations, scada, sensor-faults, thermal-storage |
| [`c6be7353-782a-54cf-b9f3-283f13558982`](c6be7353-782a-54cf-b9f3-283f13558982/) | black-box-diagnosis, experiment-design, observation-budget, python, query-optimizer, sql |

```
<uuid>/
├── task.toml         runner manifest
├── instruction.md    objective the agent reads
├── environment/      sandbox image, with a service sidecar where the task uses one
├── tests/            verifier, hidden from the agent
├── solution/         reference solution
└── trials/
    └── opus-5-5/     Claude Code trials with claude-opus-5-5
        └── <trial>/  one scored rollout
```

## Reproduction

Each task directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image (four of the five also run a simulator or service sidecar the agent reaches over the network), `tests/` the verifier, and `solution/` the reference solution. The trialsabove were produced with:

```bash
harbor run -p <task-dir> -a claude-code -m anthropic/claude-opus-5-5
```

Run `harbor run -p <task-dir> -a oracle` to score a task's reference solution.

## Cite

A citation for nexus will be published here once it releases its first evidence-backed dataset. The grounding benchmark it builds on is Terminal-Bench.

```bibtex
@misc{terminalbench2026,
  title        = {Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces},
  author       = {Merrill, Mike A. and Shaw, Alexander G. and Carlini, Nicholas and others},
  year         = {2026},
  eprint       = {2601.11868},
  archivePrefix= {arXiv},
  url          = {https://arxiv.org/abs/2601.11868}
}
```

## Contact

nexus is built by [Ethara.AI](https://github.com/Ethara-Ai).

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
