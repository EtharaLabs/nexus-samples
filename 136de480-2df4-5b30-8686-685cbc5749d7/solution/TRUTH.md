<!-- FORGE-CANARY-BEGIN -->
<!-- FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-END -->

# Ground truth

GENERATED SECTION. DO NOT HAND-EDIT.

Design id `136de480-2df4-5b30-8686-685cbc5749d7`, slot 7, archetype `build`, category `domain-expertise-depth`.

Expected reports come from `tests/sta_ref.py` over the generator's structured model; the oracle `solution/sta.py` is a separately written text parser and analyser whose reports agree with the reference within 1e-6 ns on every hidden family (recorded in the run's feasibility evidence). Every rule the reference applies is stated in `instruction.md` or cited from Liberty NLDM and SDC 2.1 (`derivation_table` in `solution/grounding.yaml`). The two designs under `/app/design/` and `/app/design/example/` are parsing samples only: no report, slack, or other reference number for them ships anywhere in the environment, and neither is graded.

## Deliverables

- `D1`: `/app/out/136de480-2df4-5b30-8686-685cbc5749d7_D1_sta.py`

## Golden trajectory

1. Parse the Liberty subset (units, `lu_table_template` variable orders and breakpoints, `wire_load`, pins, `ff` and `latch` groups, timing arcs and constraint tables), the structural Verilog, and the SDC subset; exit 2 on any malformed or undefined input. Deliverable `D1`; satisfies `R16`.
2. Evaluate every NLDM table in its template's variable order with linear interpolation and linear extrapolation, and build net loads from pin capacitance, `set_load`, and the default wire load. Deliverable `D1`; satisfies `R2`, `R3`, `J1`.
3. Mark the clock network from each clock source and generated-clock pin, recursively for a generated clock whose source register runs on another generated clock; derive each generated waveform from its master through `-divide_by`, `-multiply_by`, or `-edges`; propagate late and early clock arrivals with clock derates, recording the arc input that set each arrival with the stated tie rule, or use ideal zero latency and `set_clock_transition`. Deliverable `D1`; satisfies `R5`, `R27`.
4. Propagate late and early arrivals and slews per pin, transition, and launch group (launching clock, edge, and exception state) in one topological pass through the unateness of every arc, with data derates, so the cost grows with the arrivals kept rather than with the number of launch groups times the graph. Deliverable `D1`; satisfies `R11`, `R26`, `J7`.
5. Pair launch and capture edges over the common period of the two periods taken as exact rationals, shift setup by multicycle setup at the capture period, and take the hold relationship as the setup relationship minus the smaller of the two periods minus the multicycle hold multiplier times the launch period. Deliverable `D1`; satisfies `R8`, `R28`.
6. Time setup with late data and the early capture clock and hold with early data and the late capture clock; trace the launch and capture clock paths through every generated-clock source register, credit CPPR at their last common pin as its late minus early arrival, and credit nothing where the two paths cross that pin with opposite transitions. Deliverable `D1`; satisfies `R4`, `R24`, `R23`.
7. Time latches at the opening edge with borrowing bounded by the open window less the setup constraint and never below 0, launch Q at the latch's own opening edge from the enable and from every borrowing D arrival, so a chain of borrowing latches passes time from latch to latch; latches on a generated clock use its own edges, derates, and CPPR. Deliverable `D1`; satisfies `R10`, `R19`, `R25`, `R29`, `R30`.
8. Re-time the worst five register and port setup endpoints along the path that set each one's graph slack, with the slew propagated along that path and the late data derate, and report `pba_setup`. Deliverable `D1`; satisfies `R31`.
9. Report endpoints, WNS and TNS, arrivals, borrow, and `pba_setup` in the stated schema, computing everything from the given files. Deliverable `D1`; satisfies `R14`, `J9`.

## Rubric

| Item | Obligation | Dimension | Weight | Negate | Class | Mode | Criterion |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `R2` | D1 | outcome | 1 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` within `1e-6` ns of the reference on one hidden ideal-clock single-clock design without exceptions or derates. |
| `R3` | D1 | outcome | 1 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].hold` within `1e-6` ns of the reference on one hidden ideal-clock single-clock design without exceptions or derates. |
| `R4` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on four hidden propagated-clock designs whose clock tree runs three or four buffer levels deep and reconverges through a gate under clock-network `set_timing_derate` factors, where the late and early clock paths part at the reconvergence and the CPPR credit sits at least three buffer levels below the clock source. |
| `R5` | D1 | coverage | 5 | false | VALUE | compiled | D1 reports setup and hold slack within `1e-6` ns of the reference for every endpoint captured by the generated clock `gclk` on four hidden designs that derive `gclk` from a propagated master through `create_generated_clock` with `-divide_by`, `-multiply_by`, or `-edges`. |
| `R8` | D1 | outcome | 1 | false | VALUE | compiled | D1 reports `endpoints[e].hold` within `1e-6` ns of the reference for every endpoint whose hold slack a `set_multicycle_path -setup` exception changes, with or without a matching `-hold` exception, on one hidden propagated-clock design. |
| `R10` | D1 | coverage | 5 | false | VALUE | compiled | D1 reports every latch's `borrow` and every `endpoints[e].setup` within `1e-6` ns of the reference on four hidden propagated-clock designs under clock and data `set_timing_derate` factors whose level-sensitive `DLATX1` latches borrow time up to the open-window borrow limit. |
| `R11` | D1 | outcome | 1 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on one hidden propagated-clock design under data-path `set_timing_derate -early` and `-late` factors without clock derates. |
| `R14` | D1 | outcome | 1 | false | VALUE | compiled | D1 writes `R` as one JSON object whose keys are exactly the eight report keys, each holding the value type the instruction's Report section states, and reports `wns_setup`, `tns_setup`, `wns_hold`, and `tns_hold` within `1e-6` ns of the reference on one hidden propagated-clock single-clock design with negative setup slack. |
| `R16` | D1 | robustness | 1 | false | EFFECT | compiled | D1 exits 2 and leaves `R` unwritten for one hidden input carrying one defect drawn per run from a library syntax error, a netlist instance of an undefined cell, a netlist connection to an undefined pin, and an SDC object query that matches nothing, while it exits 0 and writes `R` for the same input without the defect. |
| `R19` | D1 | coverage | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names, every endpoint slack, every `borrow`, and every `arrivals` entry within `1e-6` ns of the reference, `null` included, on four hidden designs where level-sensitive latches on the master clock capture data launched by the generated clock under `set_multicycle_path -setup`, with CPPR on a reconvergent propagated clock tree. |
| `R23` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on six hidden propagated-clock designs whose last common clock pin carries opposite transitions on the launch and capture paths. |
| `R24` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on four hidden propagated-clock designs whose clock tree reconverges through a gate whose two inputs arrive at exactly the same time, so the clock-path tie rule decides the last common pin and the CPPR credit. |
| `R25` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names, every endpoint slack, every `borrow`, and every `arrivals` entry within `1e-6` ns of the reference, `null` included, on four hidden designs whose level-sensitive latches are enabled by the generated clock, capture data under `set_multicycle_path -setup`, and launch Q into the generated-clock domain, with CPPR on a reconvergent propagated clock tree. |
| `R26` | D1 | constraints | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names, every endpoint slack, every `arrivals` entry, every `borrow`, every `pba_setup` value, `wns_setup`, and `wns_hold` within `1e-6` ns of the reference, `null` included, on three hidden designs of at least 20000 timing-graph pins with eight primary clocks of distinct periods, four generated clocks one of them derived from another, and at least 40 `-through` exceptions, finishing each run within the 20 s limit. |
| `R27` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on four hidden propagated-clock designs with a generated clock derived from another generated clock, where a launch and capture clock path pair runs through both source registers and shares pins upstream of both. |
| `R28` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports exactly the reference endpoint names and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on four hidden propagated-clock designs whose two clocks have a period ratio that is not an integer, under `set_multicycle_path -setup` and `-hold` exceptions between the two clocks. |
| `R29` | D1 | coverage | 5 | false | VALUE | compiled | D1 reports every latch's `borrow`, the `arrivals` entry of every latch Q pin, and every `endpoints[e].setup` within `1e-6` ns of the reference on four hidden propagated-clock designs with a chain of at least three level-sensitive latches in which every latch borrows time and passes its D arrival to the next latch through D to Q. |
| `R30` | D1 | coverage | 5 | false | VALUE | compiled | D1 reports every latch's `borrow` and every `endpoints[e].setup` and `endpoints[e].hold` within `1e-6` ns of the reference on four hidden designs whose level-sensitive latches are enabled by a generated clock on a propagated tree under clock and late data `set_timing_derate` factors, with a nonzero CPPR credit at a borrowing latch. |
| `R31` | D1 | outcome | 5 | false | VALUE | compiled | D1 reports `pba_setup` for exactly the five worst register and port setup endpoints and every `endpoints[e].setup` within `1e-6` ns of the reference on four hidden propagated-clock designs where path-based re-timing moves at least two of those slacks by at least `1e-3` ns. |
| `J1` | D1 | constraints | 1 | true | ABSENCE | judged | D1 `/app/out/136de480-2df4-5b30-8686-685cbc5749d7_D1_sta.py` takes a cell delay, slew, or constraint value from a constant tuned to a design or library instead of looking it up in the library's NLDM tables at run time. |
| `J7` | D1 | process | 1 | false | INVARIANT | judged | D1 propagates one late and one early arrival per pin, transition, and launching group in topological order over its timing graph instead of enumerating paths. |
| `J9` | D1 | constraints | 1 | true | ABSENCE | judged | D1 embeds a report, slack, arrival, borrow, or critical path for any design instead of computing it from the files it is given. |

## Grid cells without an item

- D1 / craft: every compiled item parses the whole report and fails on a missing, extra, or mistyped report key, pba_setup included, so report shape is graded inside each item; no separate craft check is the sole rejector of a known-wrong control (oracle_removal_rework.grid, kept by fairness_scale_rework.grid)

## Hidden cases

fresh seed per verifier run (secrets.randbits(48), passed to the single Reward Kit run through REWARD_SEED and logged to /logs/verifier/seeds.json); every case is drawn by tests/gen_design.py pick_case, which resamples until the family's targeting predicate holds, no decision the report depends on lies within 1e-8 ns of a tie, no exact data-merge tie with different predecessors lies on a path the report reads (CPPR launch traces and the S22 re-timed paths; ties between the two transitions of a pin fed straight from an input port are equivalent and not counted), and no worst-5 membership or traced transition is decided by an exact slack tie; hard families carry weight 5 and guards weight 1 with one case each; guard-sensitive constructs (set_output_delay endpoints, distinct -min input delays, multicycle -setup without -hold on registers, the -data -early derate, the TNS keys) occur only in their guard's family or are not graded elsewhere, so each guard stays the sole rejector of its control. 59 graded D1 cases: hard families `R4`, `R5`, `R10`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R28`, `R29`, `R30`, `R31` at weight 5 and one-case guards `R2`, `R3`, `R8`, `R11`, `R14`, `R16` at weight 1.

- `R2` (guard): 1 x `setup`
- `R3` (guard): 1 x `hold`
- `R4` (hard): 4 x `cppr_deep`
- `R5` (hard): 4 x `generated`
- `R8` (guard): 1 x `mcp_hold`
- `R10` (hard): 4 x `latch_derate`
- `R11` (guard): 1 x `derate`
- `R14` (guard): 1 x `summary`
- `R16` (guard): 1 x `malformed`
- `R19` (hard): 4 x `latch_gen_mcp`
- `R23` (hard): 6 x `cppr_opposite`
- `R24` (hard): 4 x `cppr_tie`
- `R25` (hard): 4 x `latch_on_gen`
- `R26` (hard): 3 x `perf`
- `R27` (hard): 4 x `gen_of_gen`
- `R28` (hard): 4 x `mcp_ratio`
- `R29` (hard): 4 x `latch_chain`
- `R30` (hard): 4 x `latch_gen_derate`
- `R31` (hard): 4 x `pba`

## Reward

`tests/test.sh` scores one stage. When D1 is absent, empty, or does not byte-compile it writes reward 0.0 for `reward`, `test_output`, and `judge` inline and runs neither Reward Kit nor the judge, so the negated judged items never pay on an absent D1. Otherwise it runs Reward Kit once over `tests/test_output.py`, `tests/reward.toml`, and `tests/judge.toml`; a Reward Kit failure leaves no reward file and is a verifier error, never a pass.

`tests/reward.toml` fixes the carrier weights at test_output 9 and judge 1: the reward is 0.9 times the weighted mean of the compiled items in `tests/test_output.py` (item weights summing to 71) plus 0.1 times the weighted mean of the judged items in `tests/judge.toml` (item weights summing to 3) under the `codex` agent judge, model `openai/gpt-5.6-sol`, guard `penalize`. Reward Kit rounds each mean and the reward to four decimals. A run that fails only the guard `R16`, with the judge at 1.0, scores 0.9873; a run that fails only the hard item `R26` scores 0.9366. A trial passes only when its reward is exactly 1.0; the mean reward is reported beside the pass rate.

`discrimination_weight = 1.0`: task.toml declares discrimination_weight 1, the widest share item 2b.2 admits; the reward descends by 0.9 x each failed compiled item's share of 71 (a hard family 5/71, a guard 1/71) and 0.1 x each failed judged item's share of 3, and an absent, empty, or non-compiling D1 scores 0.0 with no Reward Kit run and no judge call.

## Rejected routes

- `KW-ideal-clock` ignore set_propagated_clock: rejected by `R4`, `R5`, `R8`, `R10`, `R11`, `R14`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R28`, `R29`, `R30`, `R31`
- `KW-no-cppr` no CPPR credit: rejected by `R4`, `R10`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R29`, `R30`, `R31`
- `KW-cppr-opposite` credit CPPR at the last common pin despite opposite transitions: rejected by `R23`, `R25`, `R29`, `R30`
- `KW-mcp-hold-unshifted` no SDC default hold shift under multicycle setup without -hold: rejected by `R8`
- `KW-no-borrow` no latch time borrowing: rejected by `R10`, `R19`, `R29`, `R30`
- `KW-latch-master-edge` launch a latch from the master clock edge when the source is a generated clock: rejected by `R19`
- `KW-no-derate` ignore set_timing_derate: rejected by `R4`, `R10`, `R11`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R29`, `R30`, `R31`
- `KW-setup-only` hold computed from late arrivals: rejected by `R3`, `R4`, `R5`, `R8`, `R11`, `R14`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R28`, `R30`
- `KW-output-delay-added` add set_output_delay -max to the required time instead of subtracting it: rejected by `R2`
- `KW-input-delay-min-ignored` launch an input port's early arrival at its -max input delay: rejected by `R3`
- `KW-data-early-derate-ignored` apply -early derate factors to clock-network arcs only: rejected by `R11`
- `KW-tns-all-slacks` TNS sums every endpoint slack, positive ones included: rejected by `R14`
- `KW-accept-malformed` exit 0 with a report on malformed input: rejected by `R16`
- `KW-parses-only` parse the inputs and write an empty report: rejected by `R2`, `R3`, `R4`, `R5`, `R8`, `R10`, `R11`, `R14`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R28`, `R29`, `R30`, `R31`
- `KW-hold-capture-period` hold relationship S - PC - N_hold x PL (capture period only) instead of S20: rejected by `R5`, `R19`, `R25`, `R26`, `R27`, `R28`, `R30`
- `KW-naive-per-launch-group` exact analysis that re-propagates the whole timing graph once per launch group: rejected by `R26`
- `KW-gen-of-gen-near-source` trace a generated-of-generated clock path only to the nearer source register: rejected by `R26`, `R27`
- `KW-mcp-integer-ratio` pair edges by the floor of the period ratio instead of the rational common period: rejected by `R26`, `R27`, `R28`
- `KW-latch-chain-no-through-d` a latch Q takes no through-D arrival when its D was itself launched through a latch: rejected by `R29`
- `KW-latch-gen-no-cppr` no CPPR credit at a latch on a generated clock: rejected by `R25`, `R30`
- `KW-pba-graph-slew` report the graph-based setup slack as pba_setup: rejected by `R26`, `R31`
- `KW-pba-no-derate` re-time the path with path slews but no derates: rejected by `R26`, `R31`
- `KW-opus55-v4-d1` the Opus 5.5 v4 trial D1 (sha256 a119f2fa, 48 [REDACTED] tokens restored to {}): rejected by `R2`, `R3`, `R4`, `R5`, `R8`, `R10`, `R11`, `R14`, `R19`, `R23`, `R24`, `R25`, `R26`, `R27`, `R28`, `R29`, `R30`, `R31`
- `KW-gpt61sol-d1` the GPT-6.1 Sol trial D1 (sha256 f34d9836); its bytes are absent from the run and from every checked path, so it is not re-measured (named gap KW_GPT61SOL_D1_BYTES_ABSENT); last measured 0.5098 under contract afcfc571: rejected by `R4`, `R19`, `R23`, `R24`, `R25`
- `KW-J1` hard-code library delay values tuned to the sampled designs: rejected by `J1`
- `KW-J7` enumerate every path from every start point: rejected by `J7`
- `KW-J9` return a stored report when the inputs match a sample design: rejected by `J9`
