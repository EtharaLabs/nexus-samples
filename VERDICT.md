# VERDICT

CRUCIBLE report for run `crucible-dhawal-bathre-ethara-ai-20261030t000000z-audit`, audit of the two sealed task bundles staged under `/Users/macbookpro/Documents/ship`: `136de480-2df4-5b30-8686-685cbc5749d7` (NLDM graph-based static timing analysis, author `kanishk.singh`) and `8263dbf4-358b-52b2-8ff0-2b26ffcafa67` (exactly-once session-window streaming engine, author `dhawal.bathre`, FORGE run `forge-dhawal-bathre-ethara-ai-20261029t084806z-c525f3`), each with one author-side Claude Opus 5 rollout, 2026-10-30.

## Executive summary

- ✅ Stream `8263dbf4` discrimination is strong and independently reproduced: `solution/reference.py` and the independent `solution/reference_alt.py` are byte-identical across 12 seeds × 2 configs × clean / single-crash / double-crash; the embedded reference in `tests/test_output.py` matches `reference.py` verbatim; and the described mutants MUT-GC-EARLY and MUT-SORT-ORDER diverge from the reference on every seed, so the C1/C2 weight-5 byte gates bite.
- ✅ STA `136de480` grader is well separated: 18 compiled `R`-families (hard weight 5, guards weight 1) plus three judged items, with `TRUTH.md` mapping 24 named wrong-answer routes each to the items that reject it, and every graded check tracing back to an instruction rule.
- ✅ Rewards recompute exactly from each rollout's own records (STA `0.9×0.7606 + 0.1×1.0 = 0.7845`; stream `(9×0.5641 + 1×0.8235)/10 = 0.59`); both verifiers run in a separate image, non-root, and the STA design tree is read-only with a verified `SHA256SUMS`.
- 🟡 Stream `8263dbf4` carries a documentation/rollout mismatch: `README.md` says the judged carrier is "deferred to pilot (no credential this run)", yet the shipped verifier record shows the `codex` judge (`openai/gpt-6.1-sol`) ran and scored 0.8235 (G-JUDGE-DEFERRAL-MISMATCH).
- 🟡 STA `136de480` states its hidden-case count three ways — 36 (`provenance.yaml`), 59 (`task.toml`, `grounding.yaml`, `TRUTH.md`), and 58 (the shipped verifier run) (G-CASE-COUNT).
- 🟡 STA `136de480` ships uninitialized FORGE canary slots (all four are 64 zeros) and `attestation-unavailable` ancestry/event digests (G-CANARY-STALE); the stream verifier installs `harbor-rewardkit==0.2.3` without a hash pin where the STA verifier uses `--require-hashes` (G-ENV-PIN).
- 🟢 The two bundles pin different `python:3.13-slim-bookworm` digests and dockerfile frontends; both are pinned, so this is drift to align, not an exposure (G-BASE-DRIFT).
- Gate summary: both bundles are structurally sound with aligned statements and discriminating graders; the open items are a stale README claim, a case-count reconciliation, inert canary/attestation metadata, and a missing counted pilot — all addressable without reworking the task bytes.

## Disposition

STALE — retained for a counted pilot and metadata cleanup (both bundles)

## Findings

### Grader discrimination (class 19)

- ✅ G-STREAM-DUAL-REF, acknowledged clean (`8263dbf4`): `reference.py` (linear-scan) and `reference_alt.py` (bisect interval-index, independent checkpoint format) produce byte-identical output over 12 seeds, both configs, clean and across one and two `--resume` restarts — reproduced in this audit — so the graded bytes are determined by the spec, not one implementation.
- ✅ G-STREAM-MUTANTS, acknowledged clean (`8263dbf4`): the embedded reference matches `solution/reference.py` verbatim; MUT-GC-EARLY (`>=` at close) and MUT-SORT-ORDER (processing order) each diverge from the reference on every sampled seed, so C1/C2 reject any miscorrecting or non-exactly-once engine.
- ✅ G-STA-ROUTES, acknowledged clean (`136de480`): `TRUTH.md` maps 24 named wrong-answer routes (ideal-clock, no-CPPR, opposite-transition credit, unshifted multicycle hold, integer-ratio edge pairing, graph-slew PBA, …) each to the `R`-items that reject it; each guard is declared the sole rejector of its construct.

### Statement and grader integrity (class 18)

- 🟡 G-JUDGE-DEFERRAL-MISMATCH, retained (`8263dbf4`): `README.md` ("the judged carrier is deferred to pilot (no credential this run) and, being ≤10%, never gates") contradicts the shipped `verifier/reward-details.json`, where the `codex` `AgentJudge` ran on `openai/gpt-6.1-sol`, scored 14 criteria to 0.8235, and contributed its 10% weight to the recorded 0.59. Reconcile the prose with the artifact; being ≤10% it never gates either way.
- ✅ G-STMT-RECONCILE, acknowledged clean (both): every compiled and judged criterion maps to an instruction rule — STA rules 1–10 and the Report schema to `R2`–`R31`/`J1`/`J7`/`J9`; stream rules 1–5 and the exactly-once contract to `C1`–`C15`/`J1`–`J14` — and the hidden STA 20 s speed budget is stated by design.

### Domain integrity and reward provenance (class 6)

- 🟡 G-CASE-COUNT, retained (`136de480`): the hidden-case count reads 36 (`provenance.yaml`), 59 (`task.toml`, `grounding.yaml` total, `TRUTH.md`), and 58 (the shipped verifier `cases.json`). The grounding item table sums to 59, so `provenance.yaml` is stale and the 58/59 run delta needs a note.
- 🟡 G-CANARY-STALE, retained (`136de480`): all four `FORGE-CANARY-SLOT-*` values are 64 zeros in `TRUTH.md`, `policy.yaml`, and `grounding.yaml`, and `provenance.yaml` carries `attestation-unavailable` for both ancestry and event digests, so canary-leak detection and attestation are inert.
- ✅ G-REWARD-PROVENANCE / G-ROLLOUT-ISOLATION, acknowledged clean (both): each recorded reward recomputes from that rollout's own `reward-details.json` under `weighted-mean(test_output=9, judge=1)`; the STA design tree is `chmod a-w` with a build-time `sha256sum -c`, and no trajectory writes a solution or verifier path.

### Supply-chain and environment build (class 5 / 20)

- 🟡 G-ENV-PIN, retained (`8263dbf4`): the verifier image runs `pip install harbor-rewardkit==0.2.3` from PyPI at build with no hash pin, unlike `136de480`, whose verifier resolves every wheel and Reward Kit 0.2.4 under `--require-hashes` from a vendored, SHA-checked Harbor archive.
- 🟢 G-BASE-DRIFT, retained (both): the bundles pin different `python:3.13-slim-bookworm` digests (`sha256:e32be0e5…` vs `sha256:281d39ff…`) and dockerfile frontends (`1.12` vs `1.11.1`); both are pinned, so this is drift to align.
- ✅ G-ISO-STRUCTURE / G-ENV-REGISTRY, acknowledged clean (both): multi-stage builds, non-root runtime users (STA agent `1000`, verifier `1001`; stream agent/verifier `1000`), `environment_mode = "separate"`, pinned codex `0.164.0` binaries verified by SHA-256, and no credential needed to pull the pinned bases.

## Coverage gaps

- No signed external pilot and no in-bundle oracle rollout for either task; the only shipped rollout per bundle is an author-side Opus 5 probe (STA 0.7845 with an `AgentTimeoutError`, stream 0.59), so pass@1 = 0 and the oracle-pass feasibility in `TRUTH.md`/`README.md` is asserted, not demonstrated in-bundle.
- Image builds and a `grype`/SBOM scan were not run in this audit, so STA `136de480`'s `linux/amd64` buildability and both images' vulnerability counts are unverified; the stream image labels are `proprietary` with no SBOM shipped.
- Stream `8263dbf4` `provenance.yaml` carries `contamination_screen: HOLD:PILOT_REQUIRED reason screening-unverified (no ENGRAM roots projected)`, so exclusion / near-duplicate screening resolves against no named root.
- The judged carriers depend on reaching `chatgpt.com`/`auth.openai.com`; being ≤10% of reward they never gate, but a network-isolated verifier run would score judge 0.

## Escalations

- stream `8263dbf4`: reconcile `README.md` with the shipped judged run (remove the "deferred to pilot" language or document the `gpt-6.1-sol` credential) and record one counted pilot through `solve.sh` to confirm the oracle reaches 1.0.
- STA `136de480`: correct `provenance.yaml` to the 59 the grounding declares (and note the 58/59 run delta), initialize or strip the FORGE canary slots and attestation digests, and record a counted oracle pilot within the 20 s/case budget.
- Both: align the base-image digest and dockerfile frontend, and bring the stream verifier to `--require-hashes` parity with the STA verifier before a counted run.

## Flag legend

- 🔴 retained finding that caps the bundle outcome; 🟡 retained finding to fix or accept; 🟢 low-severity retained finding; ✅ acknowledged clean.
