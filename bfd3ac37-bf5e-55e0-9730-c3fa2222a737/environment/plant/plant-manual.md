# Northfield district heating plant: operator manual

## Network map

```
                 +-------------------- near branch --------------------+
                 |   S1        S2        S3                             |
   PLANT --------+                                                      |
   B1 B2 B3      |                                                      |
   storage tank  +--[ZT-120 valve]---- far branch, 600 t supply line ---+
   pumps, bypass                         S4        S5        S6
```

- **Plant.** Three boilers (B1, B2, B3), one heat-storage tank, the network pumps, and a plant bypass that returns any pump flow the branches do not take straight to the plant return (`FT-130`).
- **Near branch.** Substations S1, S2, S3, close to the plant. Supply water reaches them in about 0.2 hours. The near branch sits nearest the pumps: when the pumps cannot meet the whole call, the far branch receives what is left.
- **Far branch.** Substations S4, S5, S6, behind the far-branch control valve (`ZT-120`). The far supply line holds about 600 t of water, so supply water reaches the far substations after 600 t divided by the far-branch flow: between 1 and 3 hours.
- **RTUs.** `RTU-PLANT`, `RTU-BLR` (boilers), `RTU-FAR` (far-branch valve station), and one RTU per substation, `RTU-S1` to `RTU-S6`.

## Tags

| Tag | RTU | Unit | Measures |
|---|---|---|---|
| `TT-100` | RTU-PLANT | C | supply temperature leaving the plant |
| `TT-101` | RTU-PLANT | C | return temperature entering the plant |
| `FT-100` | RTU-PLANT | kg/s | network pump flow |
| `FT-110` | RTU-PLANT | kg/s | near-branch flow (S1 to S3) |
| `FT-130` | RTU-PLANT | kg/s | plant bypass flow (pump flow the branches do not take) |
| `PT-100` | RTU-PLANT | bar(g) | pump inlet pressure |
| `LT-200` | RTU-PLANT | % | storage tank level (state of charge) |
| `JT-200` | RTU-PLANT | MW | storage tank net heat rate, positive while charging |
| `SC-100` | RTU-PLANT | fraction | network pump speed |
| `TT-AMB` | RTU-PLANT | C | ambient temperature at the plant |
| `JT-B1, JT-B2, JT-B3` | RTU-BLR | MW | boiler heat output |
| `FQ-B1, FQ-B2, FQ-B3` | RTU-BLR | MW | boiler fuel input (net calorific value) |
| `FT-120` | RTU-FAR | kg/s | far-branch flow (S4 to S6) |
| `ZT-120` | RTU-FAR | % | far-branch control valve position |
| `TT-S1 ... TT-S6` | RTU-S1 ... RTU-S6 | C | substation primary return temperature |
| `FT-S1 ... FT-S6` | RTU-S1 ... RTU-S6 | kg/s | substation primary flow |
| `JQ-S1 ... JQ-S6` | RTU-S1 ... RTU-S6 | MW | substation heat meter |

## Customers and substations

- A customer's heat load is UA x (indoor temperature - ambient temperature), with the indoor temperature of CONTRACT.md Annex A, and UA per substation in the parameter ranges below.
- Each substation's secondary (building-side) return temperature rises from its no-load value by 12 K at design load, where design load is UA x 40 K, in proportion to load.
- Each substation controller sets its primary flow so that its primary return temperature is the secondary return + 0.35 x (arriving supply - secondary return) while it can draw the flow it calls for.
- Substation heat exchangers have an effectiveness of 0.92.
- Supply water loses about 0.012 K per K of (supply temperature - 8 C) per hour of transport. Return water loses about 1.5 K on its way back to the plant.

## Boilers

| Boiler | Capacity, MW | Rough full-load efficiency | Excess-air ratio | Condensing |
|---|---|---|---|---|
| B1 | 7.5 to 7.7 | 0.88 | 1.08 | yes |
| B2 | 8.7 to 8.9 | 0.93 | 1.20 | no |
| B3 | 7.5 to 7.7 | 0.88 | 1.10 | yes |

- Efficiencies are heat output over fuel input on the net calorific value basis, so a condensing boiler can exceed 1.0.
- Part load lowers efficiency by about 0.03 x (1 - load fraction) squared.
- Condensing operation: B1 and B3 recover latent heat when the plant return temperature is below the flue-gas dew point, dew point C = 68 - 40 x (excess-air ratio - 1).
- Boilers in service load in the order of the `boilers` setpoint list.

### Fault codes

| Code | Meaning |
|---|---|
| E-12 | burner flame failure; the boiler trips and restarts |
| E-20 | low water pressure in the boiler circuit |
| E-31 | flue-gas temperature high |
| E-44 | boiler feed pump fault |

## Heat-storage tank

- Capacity 118 to 122 MWh; charge and discharge up to 14 MW.
- Standing loss about 0.2% of the stored energy per hour.
- The tank starts the run at 40% charge. `LT-200` reports its state of charge.
- The network pumps draw their suction from the tank (see `pump-datasheet.md`).

## Initial state at plant hour 0

Supply temperature 90 C, pump speed 0.70, boilers in service B2, B1, B3 (in that loading order), tank rate 0 MW.

## Parameter ranges

The as-built values lie within these ranges; the exact values were not recorded.

| Parameter | Range |
|---|---|
| UA, each of S1 to S3 | 0.1194 to 0.1206 MW/K |
| UA, each of S4 to S6 | 0.1294 to 0.1306 MW/K |
| No-load secondary return, S1 to S3 | 32.7 to 33.3 C |
| No-load secondary return, S4 to S6 | 45.7 to 46.3 C |
| Network pump flow at full speed | 250 to 370 kg/s |
| Tank capacity | 118 to 122 MWh |
| Boiler capacities | as in the boiler table |
| Pump suction static head at a full tank | 1.55 to 1.6 bar |
| Cold-snap low (forecast) | -15.15 to -14.85 C |
