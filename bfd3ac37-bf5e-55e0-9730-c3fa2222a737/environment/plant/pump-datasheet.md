# Network pump: datasheet extract

## Suction

- The pumps draw from the bottom connection of the heat-storage tank. The static head at the pump suction rises with the tank's state of charge, from 0 bar at an empty tank to the as-built full-tank value in `plant-manual.md` (Parameter ranges).
- The suction line loses 0.30 bar at full speed, in proportion to speed squared.
- `PT-100` reports the pump inlet pressure as gauge pressure.
- Atmospheric pressure at the plant: 1.013 bar.

## NPSH required

NPSH required, expressed as pressure in bar, against pump speed (fraction of full speed). Between rows, NPSH required = 0.15 + 1.9 x speed^8 bar.

| Speed | NPSH required, bar |
|---|---|
| 0.30 | 0.150 |
| 0.35 | 0.150 |
| 0.40 | 0.151 |
| 0.45 | 0.153 |
| 0.50 | 0.157 |
| 0.55 | 0.166 |
| 0.60 | 0.182 |
| 0.65 | 0.211 |
| 0.70 | 0.260 |
| 0.75 | 0.340 |
| 0.80 | 0.469 |
| 0.85 | 0.668 |
| 0.90 | 0.968 |
| 0.95 | 1.410 |
| 1.00 | 2.050 |

## Water vapour pressure

Linear between rows.

| Water temperature, C | Vapour pressure, bar |
|---|---|
| 40 | 0.0738 |
| 45 | 0.0959 |
| 50 | 0.1235 |
| 55 | 0.1576 |
| 60 | 0.1994 |
| 65 | 0.2503 |
| 70 | 0.3119 |
| 75 | 0.3858 |
| 80 | 0.4739 |

## Duty

The pump is rated for continuous duty at any speed from 0.30 to 1.00. Operation is safe while the absolute pressure at the pump inlet stays above NPSH required plus the vapour pressure of the water it pumps.
