# Diesel genset: datasheet extract (G1 and G2)

## Rating

- Electrical rating 3.0 MW continuous, at 50 Hz.
- Fuel: diesel, priced per MWh of fuel on the net calorific value basis (CONTRACT.md Annex B).

## Fuel consumption against electrical load

Electrical efficiency is electrical output divided by fuel input. Fuel input in MW is therefore the electrical load divided by the efficiency in the table. Between rows, interpolate linearly. Specific fuel consumption is lowest near the best-efficiency load, 80 percent of rating.

| Load fraction | Load, MW | Electrical efficiency |
|---|---|---|
| 0.2 | 0.6 | 0.2823 |
| 0.3 | 0.9 | 0.3194 |
| 0.4 | 1.2 | 0.3495 |
| 0.5 | 1.5 | 0.3726 |
| 0.6 | 1.8 | 0.3887 |
| 0.7 | 2.1 | 0.3978 |
| 0.8 | 2.4 | 0.3999 |
| 0.9 | 2.7 | 0.3950 |
| 1.0 | 3.0 | 0.3831 |

## Governor

- Droop setting 4.0 percent (as-built, 3.8 to 4.2 percent): with the island bus on its own, a genset's frequency falls by 4 percent of 50 Hz, that is 2 Hz, between no load and rated load. Two gensets in service share a load change in proportion to their ratings.
- A genset's output cannot go below zero or above its rating; beyond that the island's under-frequency relays shed load. The relays act before the island frequency falls below 49.55 Hz: they drop load in proportion across all feeders rather than let it fall further.
