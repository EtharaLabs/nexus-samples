<!-- FORGE-CANARY-BEGIN -->
<!-- FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-END -->

# Ground truth

GENERATED SECTION. DO NOT HAND-EDIT.

Design dh-plant-coldsnap-ops, slot 2, archetype operate, category compositional-depth. The agent runs a simulated district-heating plant for 72 plant hours through the SCADA sidecar (environment/scada-sim) and reports what in the plant was not as it first seemed. The trial seed is a secure random choice from a pool of seeds the reference policy passed with margin at build time (environment/scada-sim/seeds.json). After the agent's container stops, the sidecar's collect step (finalize.py) replays the sidecar-held action log through the deterministic simulator and exports O1-O4 with the seed's expected incident set; tests/grade.py scores the incident report (O5). The oracle is solution/solve.sh, which runs the reference policy in solution/coldsnap_ops against the live API. One expected incident, the pump-flow limit above which the far branch hunts (operating_limit on FT-100), is deliberately left out of the plant documents; README.md defines only the operating_limit kind it is reported as. The pump datasheet rates the pump for continuous duty at any speed, and the hunt shows in the 10-second raw samples while the 15-minute telemetry mostly hides it, so finding it is the run's hardest discovery (golden trajectory step 4).

## Deliverables

- `D1`: the operated plant: the sidecar-held action log, replayed and scored O1-O4 by environment/scada-sim/finalize.py after the agent's container stops
- `D2`: /app/out/6c55cb9f-e734-5025-8e5f-43ef2f4336fa_D2_incidents.json

## Golden trajectory

1. Read CONTRACT.md, README.md, plant-manual.md, and pump-datasheet.md, then read the status and the forecast before the first control change; the cold snap arrives before the graded window. Satisfies O1, O3, J3.
2. Start charging the tank in low-tariff hours and stage the boilers so charging uses the cheapest fuel (Annex B); after each accepted change, read the telemetry before requesting the next. Satisfies O3, J4.
3. Probe the far branch at high load with a deliberate step served before hour 60, a low supply temperature at a high pump flow, after which, before the next change, the far-branch flow (pump flow less near-branch and bypass flow, FT-100 less FT-110 and FT-130) comes within 2 percent of its highest value before hour 66; take one raw-sample call over a span at that load, within 10 percent of the highest pump speed commanded before hour 66. The far-branch RTU logs only valve moves above 2%, so FT-120's logged points are censored: estimate the saturation flow by that mass balance in the telemetry, whose returned values lie within 10 percent of the flow reported. Satisfies O1, O5 (FT-120 limit), J5, J6, J7.
4. Find the flow above which the far branch hunts by a bisection on pump speed, spending one raw-sample call on the far-branch return temperatures and FT-100 after each step, since 15-minute averages hide the 6-minute hunt; the raw FT-100 samples returned include values within 10 percent of the threshold reported. Satisfies O2, O5 (FT-100 limit), J6.
5. Check every substation meter against the network heat balance to find the meter biased from the start and the one drifting from about hour 30, and compare a flow meter's readings on both sides of a logged firmware update to find the unit change; the full telemetry read before hour 72 then holds, for each of these meters, the balance values that contradict its readings. Satisfies O5, J9.
6. Check the packets' sequence numbers to find the RTU replaying an old window from about hour 24; the same telemetry returns that RTU's packets whose sequence numbers fail to advance. Satisfies O5, J9.
7. Attribute boiler-2's efficiency loss to its logged fault code by a per-boiler energy balance, not to the weather, with an event-log read that shows the B2 fault code; then load B2 last for the later tank charges and take it out of service for the window. Satisfies O3, O5, J10.
8. Report the Annex A setback substation, whose contracted night setback lowers its return, as kind contract, not as a fault; the telemetry read covers that substation's packets for every 15-minute interval of its setback hours. Satisfies O5, J11.
9. Plan the window: supply temperature and pump speed that hold every substation's return above 55 C below the hunt flow, an NPSH check in absolute pressure at a pump speed no lower than the planned one that sets the lowest tank level the discharge may reach, condensing-aware staging for boilers 1 and 3, and a tank discharge that meets heat and cost together; make the last change before hour 66 with ramps respected and at most 40 changes, then read the telemetry after its 20-minute ramp ends and before hour 66. Satisfies O1, O2, O3, O4, J8.
10. Spread the accepted raw-sample calls over each of the plant-hour phases [0, 24), [24, 48), and [48, 72), with fewer than 40 of them before hour 48, and send no request outside the documented API; keep monitoring after the plan is set, then write the incident report with one entry per subject in the README.md format. Satisfies O5, J1, J2, J12, J13.

## Controls and their planned failed sets

- Oracle: the reference policy (solution/solve.sh running solution/coldsnap_ops) passes every item O1-O5 with margin on every admitted pool seed, O5 exactly 1.0, with no rejected request.
- No-op: no API call and no incident report; reward, test_output, and judge each exactly 0.0, with no Reward Kit run and no judge call.
- Known-wrong, each failing exactly its planned set among O1-O5 on raw scores before the Rule C gate and passing its own self-check: R1 averaged telemetry only (O2, O5); R2 mild-weather extrapolation (O1, O5); R3 setback treated as fault (O5); R4 smooth fitted efficiency curve (O3); R5 weather-only fuel attribution (O3, O5); R6 trusts every stream (O5); R7 fits logged points only (O5); R8 raises pump speed without the NPSH check (O1, O2); R9 ignores the tariff (O3); one-control-at-a-time tuning (O1, O3); no monitoring after hour 20 (O5); no tank pre-charge (O1, O3).
- Anti-shortcut: blanket-safe (conservative settings safe for every seed in the documented ranges, with no experiments) fails O1 or O3 on at least 95 percent of admitted seeds; the best single fixed plan, chosen with full knowledge of the documented ranges and no per-trial discovery, scores a reward below 1.0 on at least 95 percent of admitted seeds.
- Red team: cheat-read and cheat-replay gain no item beyond an honest twin that issues the same documented API calls, and never reach reward 1.0.

## Pacing and time limit

Plant time runs at 150 real seconds per plant hour (2.5 real minutes), so the 72 plant hours of a run take 10800 s, and the agent's limit is 14400 s (4 hours; task.toml [agent] timeout_sec). Plant time starts at the agent's first API call; the sidecar paces its steps to this rate, and the collect step replays unpaced. Everything defined in plant time is unchanged: the 72-hour horizon, the fault onsets, the 20-minute ramps, the graded window hours 66 to 72, the change cap of 40, the raw-sample quota of 40, and Rule C. Draft 04dbb6d7 ran at 300 real seconds per plant hour with an agent limit of 28800 s (contract.yaml rubric.calibration_replan.pacing; recorded choices P2 and P4).

## Calibration

No plant parameter changed: the simulator, its seeded hidden ranges, and the plant documents are those of draft 04dbb6d7, apart from the `contract` kind line, the pacing sentence, and the Review section of environment/plant/README.md. contract.yaml rubric.calibration_replan.slot_2_bar (amendment 34) supersedes rubric.calibration_replan.slot_2_calibration for this slot and reads the calibration bar as the full-reward reading. A reward of exactly 1.0 needs O5 = 1.0, an incident report that matches all eight expected incidents of the trial seed, and that set's sensor subjects, onsets, and operating limits are drawn per seed (d2_expected_set), so one constant report matches the expected set of only the few seeds that share it, whatever the plan. Every fault and incident (R1-R9 and the expected set of 8), every control and its planned failed set, the raw-sample quota, the change cap, the ramps, the graded window, and every tolerance and threshold are unchanged.

Calibration bar (contract.yaml rubric.calibration_replan.slot_2_bar): the full-reward reading, the fraction of admitted pool seeds on which the best fixed plan of a full-dimension search over every documented control and schedule dimension, each across its whole documented range, paired with its best constant D2 report, reaches reward exactly 1.0 (Rule C on raw O1-O5, judge stand-in 1.0), is at most 5 percent of the admitted pool, rounded down to whole seeds (recorded choice P1). The search screens on a fixed subset of at least 60 pool seeds, verifies at least the five best distinct screened plans on the full pool, then descends one dimension at a time for at least 150 full-pool evaluations or until two full passes improve no neighbour, whichever comes later, ranks plans by the full-reward count, and compares plans on equal seed sets. The joint count of seeds meeting O1, O2, and O3 together is recorded beside each plan and never decides the bar.

Every measured figure (the pool and its admission statistics, the search, its plateau, the bar result, the best plans, the full-reward reading, the controls' outcomes, the non-regression replays, the mutant rewards, and the judge runs) stays in the run's records and is cited here by path, never restated:

- `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops-fullreward/`: every search evaluation with its plan, seed set, full-reward count, and joint count beside it, the constant-report group bound, the plateau, the bar result, and the non-regression replays
- `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops/rebuild/integration/`: the full pool regeneration with its feasibility log and manifest line, the controls' failed sets, and the one-fault mutant rewards
- `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops/rebuild/rubric/`: the J1-J13 judge runs, the cheat checks, and the request-log reconstruction proofs
- `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops-calibration-r1/` and `-r2/`: the two rounds of the superseded slot_2_calibration (round 1 failed and reverted, round 2 stopped at the document gate)
- `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops/findings.md` and `.seed/runs/<run_id>/feasibility/dh-plant-coldsnap-ops-fixedsearch/`: draft 04dbb6d7's calibration record, which stays on record

## Pass rule

A trial passes only when its reward is exactly 1.0. The reward is Reward Kit's weighted mean of test_output, the all-pass of the compiled items O1-O5, at weight 1.0 and judge, the 13 judged items J1-J13 (J2 and J13 negated), at weight 0.0 (tests/reward.toml), so it is 1.0 exactly when O1-O5 all pass and the judged items are reported without changing it; Rule C gates the contract checks on the report. O1-O4 count only when O5 = 1.0, and otherwise each scores 0.0; O5 is always scored.
