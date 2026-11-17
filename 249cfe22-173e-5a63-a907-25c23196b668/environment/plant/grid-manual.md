# Ridgeway island grid: operator manual

## Single-line diagram

```
   G1 (3.0 MW) ----+
   G2 (3.0 MW) ----+---- island bus ----+---- load groups HOSP, WATER, TELCO, MILL, TOWN, DOCK
   PV array --------+        |          |
   battery inverter +        |          +---- utility tie (to the mainland grid)
```

- **Gensets.** Two diesel gensets, G1 and G2, each rated 3.0 MW. Their efficiency curve and governor droop are in `genset-datasheet.md`. While the utility tie is open the gensets hold the island frequency: each takes its share of whatever the other sources leave, by its governor droop, between zero and its rating.
- **PV.** One PV array of about 2 MW peak, following the forecast.
- **Battery.** One battery of 11.6 to 12.4 MWh behind an inverter rated 2.4 to 2.6 MW. The battery starts the run at about 40 percent of its capacity. Charging and discharging each lose 4 percent of the energy (efficiency 0.96 each way). Standing losses are small. The EMS stops discharging at 5 percent charge and charging at 98 percent.
- **Load groups.** Six groups, each on its own feeder and meter. Group demand follows a daily pattern that repeats each day. The groups can be switched off together or singly with `shed`.
- **Utility tie.** The tie carries whatever the gensets, PV, and battery leave while it is closed. It is open from the hour CONTRACT.md Annex C gives.
- **RTUs.** `RTU-BUS`, `RTU-GEN`, `RTU-FREQ` (the frequency recorder), and one RTU per load group, `RTU-HOSP`, `RTU-WATER`, `RTU-TELCO`, `RTU-MILL`, `RTU-TOWN`, `RTU-DOCK`.

## Tags

| Tag | RTU | Unit | Measures |
|---|---|---|---|
| `F-SYS` | RTU-BUS | Hz | system frequency on the island bus |
| `PT-TIE` | RTU-BUS | MW | utility tie power, positive when importing |
| `PT-PV` | RTU-BUS | MW | PV output |
| `PT-BAT` | RTU-BUS | MW | battery power at the inverter, positive when discharging |
| `SOC-BAT` | RTU-BUS | % | battery state of charge |
| `PG-G1`, `PG-G2` | RTU-GEN | MW | genset electrical output |
| `FQ-G1`, `FQ-G2` | RTU-GEN | MW | genset fuel input (net calorific value) |
| `F-GEN` | RTU-FREQ | Hz | frequency at the genset bus (logged by exception, see README.md) |
| `PM-HOSP`, `PM-WATER`, `PM-TELCO`, `PM-MILL`, `PM-TOWN`, `PM-DOCK` | RTU-HOSP, RTU-WATER, RTU-TELCO, RTU-MILL, RTU-TOWN, RTU-DOCK | MW | load group demand meter |

Genset ids for the incident report are `G1` and `G2`; load group ids are the group names above.

### Fault codes

| Code | Meaning |
|---|---|
| E-12 | fuel pressure low; the genset trips and restarts |
| E-20 | coolant temperature high |
| E-31 | governor or speed-control fault |
| E-44 | alternator excitation fault |

## Initial state at plant hour 0

G1 and G2 at 1.8 MW each, battery power 0 MW, no PV curtailment, no group shed.

## Parameter ranges

The as-built values lie within these ranges; the exact values were not recorded.

| Parameter | Range |
|---|---|
| Genset rating, each | 3.0 MW |
| Battery capacity | 11.6 to 12.4 MWh |
| Battery inverter rating | 2.4 to 2.6 MW |
| PV peak | 1.9 to 2.1 MW |
| Governor droop setting | 3.8 to 4.2 percent |
| Load of each group | within 3 percent of its daily pattern |
