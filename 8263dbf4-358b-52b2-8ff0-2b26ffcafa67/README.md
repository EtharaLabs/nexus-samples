# stream-session-window-exactly-once

## What the agent does

The agent implements `/app/stream`, a single-threaded, deterministic streaming
engine. It consumes a JSONL trace of event and watermark messages (logical time
advances only via watermarks), maintains per-key **gap session windows**, emits
**FINAL** aggregates when a window closes, and when a **late event within allowed
lateness bridges already-FINALed sessions** emits a **RETRACT** for each
invalidated FINAL followed by one merged **re-FINAL** in a pinned canonical sort
order. Over-late events are dropped and counted. The engine checkpoints full
state atomically, prints `ACK <seq>` per event, and on `--resume` truncates the
output to the last committed emitted sequence and replays for **bit-identical,
exactly-once** continuation across a `SIGKILL`. See [instruction.md](instruction.md).

The shipped `/app/stream` is a stub that only ACKs events and writes an EOF
record; every window, retraction, checkpoint, and resume behavior is the agent's
to build. The hardness is long-horizon incremental state with weak
self-verification: a wrong GC/close inequality direction, a missed retraction
cascade, a wrong merge trigger, or a checkpoint that omits the last emitted
sequence keeps emitting plausible records and is exposed only by a full-trace
byte diff — there is no cheap closed-form self-check.

## Environment

Base image `python:3.13-slim-bookworm` (digest-pinned, multi-stage, non-root
`1000:1000`), no network. The stub `/app/stream` and `config_1`
`/app/data/config.json` are installed from `environment/`. Agent timeout 3600s.

## Verifier

Separate verifier image (`tests/Dockerfile`) preinstalling
`harbor-rewardkit==0.2.3`, baking `config_1`, and baking the pinned `codex`
binary (v0.164.0) the judge needs. `tests/test_output.py` embeds the reference
engine **verbatim** from `solution/reference.py` and runs it in-process to
produce the expected output; the agent's `/app/stream` is run as a subprocess
and compared byte for byte, clean and across chunked `--resume`/`--final`
restarts (each resume handed only the unconsumed suffix, in an isolated+deleted
temp dir), over seeded traces and two field configs (the second via `KVD_HOME`).
`tests/judge.toml` adds 14 reference-grounded judged criteria scored by a codex
`AgentJudge` (`judge = "codex"`, model `openai/gpt-6.1-sol`); the verifier
allowlists `chatgpt.com`/`auth.openai.com` and authenticates with
`CODEX_AUTH_JSON` + `REWARDKIT_FORCE_SUBSCRIPTION=1`. Reward is
`weighted-mean(test_output=9, judge=1)` with a `0.9` compilation floor; the
judged carrier is deferred to pilot (no credential this run) and, being ≤10%,
never gates.

### Compiled criteria (tests/test_output.py)

| id | dim | w | checks |
| --- | --- | --- | --- |
| C1 | outcome | 5 | clean output byte-identical to reference (primary seed) |
| C2 | robustness | 5 | crash+resume output byte-identical to reference (exactly-once) |
| C3,C6,C7,C9 | outcome/coverage | 3 | dropped-late count, RETRACT records, FINAL records, session boundaries |
| C4,C5,C8,C10 | robustness/outcome | 3 | atomic checkpoint, config_2 clean, double-crash, config_2 crash |
| C11–C15 | craft/constraints | 1 | sorted-key JSON, contiguous emit ids, determinism, crash-before-checkpoint, single EOF |

### Discrimination (author-side reward harness over the generated criteria)

| candidate | reward | note |
| --- | --- | --- |
| oracle (`reference.py`) | 1.000 | all criteria pass |
| independent (`reference_alt.py`) | 1.000 | bisect interval-index, byte-identical |
| no-op stub | 0.000 | floor |
| MUT-LATE-DROP | 0.179 | discards late events (no bridge/retract) |
| MUT-GC-EARLY | 0.410 | `>=` instead of strict `>` at window close |
| MUT-DUP-EMIT | 0.795 | checkpoint omits last emitted seq; re-emits on resume |
| MUT-SORT-ORDER | 0.410 | processing order instead of canonical |

Every named mutant drops at least 0.20 below the oracle; the two weight-5 gates
(C1 clean, C2 crash/resume) fail any miscorrecting or non-exactly-once engine.

## Layout

```
stream-session-window-exactly-once/
├── instruction.md
├── task.toml
├── environment/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── stream.py            # stub installed to /app/stream
│   └── data/config.json     # config_1
├── solution/
│   ├── reference.py         # correct engine (linear-scan)
│   ├── reference_alt.py     # independent cross-check (bisect interval-index)
│   ├── solve.sh             # oracle installer [generated]
│   ├── grounding.yaml       # single source of truth
│   ├── recompute.py         # derives solve.sh, TRUTH.md, tests/*
│   ├── policy.yaml
│   ├── provenance.yaml
│   └── TRUTH.md             # golden trajectory [generated]
└── tests/
    ├── Dockerfile           # + pinned codex binary for the AgentJudge
    ├── test.sh
    ├── reward.toml
    ├── test_output.py       # compiled criteria [generated]
    └── judge.toml           # judged criteria (codex AgentJudge) [generated]
```

## Running

```
harbor run -p <task-path> -a oracle        # reward 1.0
harbor run -p <task-path> -a terminus-2 -m <model>
```
