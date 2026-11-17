# Northfield district heating: customer contract (excerpt for the operator)

Plant hours count from 0 at the start of the run. Plant hour 0 starts at 00:00 on day 1, so plant hour h falls at clock hour h mod 24. The contract window is plant hours 66 to 72 (18:00 to 24:00 on day 3).

## Rules for the contract window

1. **Delivered heat.** The heat delivered to the six customer substations S1 to S6 during hours 66 to 72 is at least **144.0 MWh**, as delivered at the substations.
2. **Return floor.** No customer substation's actual return temperature is below **55.0 C**, sampled at 10-second resolution, for more than **10 minutes in total** during hours 66 to 72.
3. **Fuel cost.** The fuel cost of the heat delivered during hours 66 to 72 is at most **57.10 EUR per MWh delivered**, priced by Annex B as follows:
   - fuel the boilers burn during hours 66 to 72 is priced at the Annex B tariff of the hour in which it is burned;
   - heat drawn from the storage tank during hours 66 to 72 is priced at the tank's average stored cost. Each MWh put into the tank carries the Annex B cost of the fuel burned to make it (when the boilers both serve the network and charge the tank, the fuel is split in proportion to the heat each takes), and cost leaves the tank in proportion to the energy that leaves it, standing losses included;
   - the tank starts the run at 40% of its capacity carrying a stored cost of 30.00 EUR per MWh;
   - the cost per MWh is that total divided by the heat delivered under rule 1.
4. **Control changes.** At most **40 control changes** over the whole run. A control change is one accepted request to `POST /api/v1/control`. One request may set several controls; it counts as one change.
5. **Ramps.** Each change starts a **20-minute** ramp of plant time during which the changed setpoints move linearly to their new values. A control request received during a ramp is rejected and not applied, and each such request counts as a breach of rule 4.
6. **No changes in the window.** A control request received at or after plant hour 66 is rejected and not applied, and each such request counts as a breach of rule 4.

A request that the API refuses as malformed or out of range (HTTP 400) is not a control change and is not a breach. The plant keeps its last accepted settings when no request arrives.

## Annex A: contracted indoor temperatures and night setbacks

Each customer's heating is contracted to the indoor temperature below, lowered to the setback temperature during the setback hours (clock time, every day).

| Substation | Indoor C | Setback hours | Setback indoor C |
|---|---|---|---|
| S1 | 20.0 | 22:00 to 06:00 | 18.0 |
| S2 | 20.0 | 22:00 to 06:00 | 18.0 |
| S3 | 20.0 | 00:30 to 06:30 | 12.0 |
| S4 | 20.0 | 22:00 to 06:00 | 18.0 |
| S5 | 20.0 | 22:00 to 06:00 | 18.0 |
| S6 | 20.0 | 22:00 to 06:00 | 18.0 |

## Annex B: fuel tariff

EUR per MWh of fuel (net calorific value), by plant hour.

| Plant hour | Clock | EUR per MWh fuel |
|---|---|---|
| 0 | 00:00 | 28.00 |
| 1 | 01:00 | 28.00 |
| 2 | 02:00 | 28.00 |
| 3 | 03:00 | 28.00 |
| 4 | 04:00 | 28.00 |
| 5 | 05:00 | 28.00 |
| 6 | 06:00 | 46.00 |
| 7 | 07:00 | 46.00 |
| 8 | 08:00 | 46.00 |
| 9 | 09:00 | 46.00 |
| 10 | 10:00 | 46.00 |
| 11 | 11:00 | 46.00 |
| 12 | 12:00 | 46.00 |
| 13 | 13:00 | 46.00 |
| 14 | 14:00 | 46.00 |
| 15 | 15:00 | 46.00 |
| 16 | 16:00 | 74.00 |
| 17 | 17:00 | 74.00 |
| 18 | 18:00 | 74.00 |
| 19 | 19:00 | 74.00 |
| 20 | 20:00 | 74.00 |
| 21 | 21:00 | 74.00 |
| 22 | 22:00 | 74.00 |
| 23 | 23:00 | 46.00 |
| 24 | 00:00 | 28.00 |
| 25 | 01:00 | 28.00 |
| 26 | 02:00 | 28.00 |
| 27 | 03:00 | 28.00 |
| 28 | 04:00 | 28.00 |
| 29 | 05:00 | 28.00 |
| 30 | 06:00 | 46.00 |
| 31 | 07:00 | 46.00 |
| 32 | 08:00 | 46.00 |
| 33 | 09:00 | 46.00 |
| 34 | 10:00 | 46.00 |
| 35 | 11:00 | 46.00 |
| 36 | 12:00 | 46.00 |
| 37 | 13:00 | 46.00 |
| 38 | 14:00 | 46.00 |
| 39 | 15:00 | 46.00 |
| 40 | 16:00 | 74.00 |
| 41 | 17:00 | 74.00 |
| 42 | 18:00 | 74.00 |
| 43 | 19:00 | 74.00 |
| 44 | 20:00 | 74.00 |
| 45 | 21:00 | 74.00 |
| 46 | 22:00 | 74.00 |
| 47 | 23:00 | 46.00 |
| 48 | 00:00 | 28.00 |
| 49 | 01:00 | 28.00 |
| 50 | 02:00 | 28.00 |
| 51 | 03:00 | 28.00 |
| 52 | 04:00 | 28.00 |
| 53 | 05:00 | 28.00 |
| 54 | 06:00 | 46.00 |
| 55 | 07:00 | 46.00 |
| 56 | 08:00 | 46.00 |
| 57 | 09:00 | 46.00 |
| 58 | 10:00 | 46.00 |
| 59 | 11:00 | 46.00 |
| 60 | 12:00 | 46.00 |
| 61 | 13:00 | 46.00 |
| 62 | 14:00 | 46.00 |
| 63 | 15:00 | 46.00 |
| 64 | 16:00 | 74.00 |
| 65 | 17:00 | 74.00 |
| 66 | 18:00 | 74.00 |
| 67 | 19:00 | 74.00 |
| 68 | 20:00 | 74.00 |
| 69 | 21:00 | 74.00 |
| 70 | 22:00 | 74.00 |
| 71 | 23:00 | 46.00 |
