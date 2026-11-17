# Ridgeway island grid: supply contract (excerpt for the operator)

Grid hours count from 0 at the start of the run. Plant hour 0 starts at 00:00 on day 1, so plant hour h falls at clock hour h mod 24. The contract window is plant hours 66 to 72 (18:00 to 24:00 on day 3).

## Rules for the contract window

1. **Critical energy.** In each segment of hours 66 to 72 between revision effective hours (see the revision rule), the energy served to the load groups that are critical in that segment is at least that segment's contracted MWh, under the Annex A terms in force in it after every revision. With no revision effective inside the window, the segment is the whole window.
2. **Frequency.** System frequency, sampled at 1-second resolution, is outside **49.5 to 50.5 Hz** for at most **10 minutes in total** during hours 66 to 72.
3. **Cost.** The fuel plus import cost per MWh served during hours 66 to 72 is at most **139.00 EUR per MWh served**, priced by Annex B as follows:
   - fuel the gensets burn during hours 66 to 72 is priced at the Annex B fuel price, per MWh of fuel (net calorific value);
   - imports are priced at the Annex B hourly tariff of the hour in which they are drawn, and at the Annex B demand-response penalty price while a demand-response event, as revised, is in force;
   - energy drawn from the battery during hours 66 to 72 is priced at the battery's average stored cost. Each MWh put into the battery carries the Annex B cost of the supply that made it (the load and the battery share the fuel and imports that supply them, and the cost is split in proportion to the energy each takes; PV output serves the load first and carries no cost), and cost leaves the battery in proportion to the energy that leaves it, standing losses included. Energy imported during a demand-response event, as revised, enters the stored cost at the penalty price;
   - the battery starts the run at about 40 percent of its capacity carrying a stored cost of 95.00 EUR per MWh;
   - the cost per MWh is that total divided by the energy served to all load groups.
4. **Control changes.** At most **40 control changes** over the whole run. A control change is one accepted request to `POST /api/v1/control`. One request may set several controls; it counts as one change.
5. **Ramps.** Each change starts a **20-minute** ramp of grid time during which the changed set points move linearly to their new values. A control request received during a ramp is rejected and not applied, and each such request counts as a breach of rule 4.
6. **No changes in the window.** A control request received at or after plant hour 66 is rejected and not applied, and each such request counts as a breach of rule 4.

A request that the API refuses as malformed or out of range (HTTP 400) is not a control change and is not a breach. The grid keeps its last accepted settings when no request arrives.

**Revision rule.** The utility system operator may revise the Annex A and Annex C terms during the run by a message on the message channel documented in README.md. A revision binds from its effective hour onward; the terms before its effective hour stay as they were; and every rule above is read under the terms in force at each hour.

## Annex A: critical load groups and contracted critical energy

At the start of the run the critical load groups are **HOSP**, **WATER**, and **TELCO**. The other groups (**MILL**, **TOWN**, **DOCK**) are not critical. The contracted critical power of each critical group, by clock hour (every day), is below; a segment's contracted MWh is the sum of its groups' contracted power over the hours of the segment.

| Clock | HOSP, MW | WATER, MW | TELCO, MW |
|---|---|---|---|
| 00:00 | 0.638 | 0.475 | 0.301 |
| 01:00 | 0.638 | 0.475 | 0.301 |
| 02:00 | 0.638 | 0.475 | 0.301 |
| 03:00 | 0.638 | 0.475 | 0.301 |
| 04:00 | 0.638 | 0.475 | 0.301 |
| 05:00 | 0.638 | 0.523 | 0.301 |
| 06:00 | 0.638 | 0.594 | 0.301 |
| 07:00 | 0.638 | 0.594 | 0.301 |
| 08:00 | 0.693 | 0.594 | 0.301 |
| 09:00 | 0.693 | 0.594 | 0.301 |
| 10:00 | 0.693 | 0.523 | 0.301 |
| 11:00 | 0.693 | 0.523 | 0.301 |
| 12:00 | 0.693 | 0.523 | 0.301 |
| 13:00 | 0.693 | 0.523 | 0.301 |
| 14:00 | 0.693 | 0.523 | 0.301 |
| 15:00 | 0.693 | 0.523 | 0.301 |
| 16:00 | 0.693 | 0.523 | 0.301 |
| 17:00 | 0.693 | 0.594 | 0.301 |
| 18:00 | 0.693 | 0.594 | 0.301 |
| 19:00 | 0.693 | 0.594 | 0.301 |
| 20:00 | 0.638 | 0.594 | 0.301 |
| 21:00 | 0.638 | 0.523 | 0.301 |
| 22:00 | 0.638 | 0.475 | 0.301 |
| 23:00 | 0.638 | 0.475 | 0.301 |

## Annex B: fuel price, import tariff, demand-response penalty

- Fuel: **60.00 EUR per MWh of fuel** (net calorific value).
- Demand-response penalty price for imports during a demand-response event: **480.00 EUR per MWh**.
- Import tariff, EUR per MWh, by plant hour:

| Plant hours | EUR per MWh |
|---|---|
| 0 to 5 | 110.00 |
| 6 to 9 | 125.00 |
| 10 to 15 | 105.00 |
| 16 to 21 | 210.00 |
| 22 to 23 | 125.00 |
| 24 to 29 | 110.00 |
| 30 to 33 | 125.00 |
| 34 to 39 | 105.00 |
| 40 to 45 | 210.00 |
| 46 to 61 | 58.00 |
| 62 to 63 | 105.00 |
| 64 to 69 | 210.00 |
| 70 to 71 | 125.00 |

## Annex C: scheduled tie outage and demand-response events

- The utility tie is open from plant hour **62** to the end of the run.
- Demand-response events: the load group **DOCK** drops during a demand-response event. The first event runs from hour 11 to hour 14. A last event starts at an hour from 46 to 52 and runs for two hours; its start and end hours are posted in the event log as a `dr_notice` about 20 hours ahead. A demand-response event is also a period in which imports carry the Annex B penalty price.
