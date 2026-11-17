<!-- FORGE-CANARY-BEGIN -->
<!-- FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000 -->
<!-- FORGE-CANARY-END -->

# Ground truth

GENERATED SECTION. DO NOT HAND-EDIT.

Design microgrid-dispatch-outage, slot 5, archetype operate, category interactive-steerability. The agent dispatches a simulated island microgrid for 72 grid hours through the EMS sidecar (environment/ems-sim), follows the utility operator's mid-run revisions of the contract, and reports what in the grid was not as it first seemed. The trial seed is a secure random choice from a pool of seeds the reference policy passed with margin at build time (environment/ems-sim/seeds.json). After the agent's container stops, the sidecar's collect step (python3 -m plantops.finalize) replays the sidecar-held action log through the deterministic simulator and exports O1-O4 with the seed's expected incident set; tests/grade.py scores the incident report (O5). The oracle is solution/solve.sh, which runs the reference policy in solution/microgrid_ops against the live API.

## Deliverables

- `D1`: the operated grid: the sidecar-held action log, replayed and scored O1-O4 by plantops.finalize (environment/ems-sim) after the agent's container stops
- `D2`: /app/out/249cfe22-173e-5a63-a907-25c23196b668_D2_incidents.json

## Golden trajectory

1. Read CONTRACT.md, README.md, grid-manual.md, and genset-datasheet.md, then the forecast and the message channel; the utility tie opens for the outage near the end of the run. Satisfies O1, O3.
2. Charge the battery once and fit its capacity from the energy it takes, then find the minimum stable genset load with a deliberate low-load step test read from the frequency recorder, using a censoring-aware amplitude fit since the recorder logs only excursions beyond its deadband. Satisfies O2, O5 (PG-GEN limit).
3. Step the battery discharge power up and read raw samples at 1 second, since 15-minute averages hide the sag cycles of the inverter; fit the discharge power above which the output sags. Satisfies O1, O5 (PT-BAT limit).
4. Check every load meter against the energy balance to find the meter biased from the start and the one drifting from about hour 30; watch the event log for the firmware unit change. Satisfies O5.
5. Check sequence numbers and uptime counters to find the RTU replaying an old window from about hour 24. Satisfies O5.
6. Attribute the fuel rise of one genset to its logged fault code by a per-genset fuel-to-power balance, not to the PV ramp, and keep that genset out of the window. Satisfies O3, O5.
7. Cross-check the group that drops in the Annex C demand-response event against the annex and report it as kind contract, not as a feeder trip. Satisfies O5.
8. Read the message channel as it fills: take the revised tie-open hour, the extended demand-response event, and the revised critical list into the plan before they bind. Satisfies O1, O3.
9. Charge the battery from imports in the low-tariff hours that lie before the revised tie-open hour and outside the demand-response event, then set the window plan once: one genset near its best-efficiency load above the minimum stable load, battery discharge below the derate power, and the groups that are non-critical under both the old and the new list shed; make the last change before hour 66 with ramps respected and at most 40 changes. Satisfies O1, O2, O3, O4.
10. Keep monitoring after the plan is set, then write the incident report with one entry per subject in the README.md format. Satisfies O5, J1, J2.

## Pass rule

A trial passes only when its reward is exactly 1.0. The reward is 0.9 x the compiled weighted mean of O1-O5 plus 0.1 x the judged mean of J1 and J2, where Rule C gates the contract checks on the report. O1-O4 count only when O5 = 1.0, and otherwise each scores 0.0; O5 is always scored.
