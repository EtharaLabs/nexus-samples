"""Values the shipped documents state, and nothing else (plant-manual.md, genset-datasheet.md,
CONTRACT.md Annexes A to C, README.md). The reference policy reads no other constant about the plant.
"""

from __future__ import annotations

GROUPS = ("HOSP", "WATER", "TELCO", "MILL", "TOWN", "DOCK")
CRIT0 = ("HOSP", "WATER", "TELCO")
G_RATED = 3.0  # MW, plant-manual.md
BAT_CAP_RANGE = (11.6, 12.4)  # MWh, plant-manual.md parameter ranges
BAT_INV_RANGE = (2.4, 2.6)  # MW
BAT_EFF = 0.96  # one way, plant-manual.md
DROOP = 0.04  # genset-datasheet.md governor droop setting
BAND = (49.5, 50.5)  # Hz, CONTRACT.md
FUEL_PRICE = 60.0  # EUR per MWh of fuel, Annex B
DR_PENALTY = 480.0  # EUR per MWh imported during a demand-response event, Annex B
COST_CAP = 139.0  # EUR per MWh served, CONTRACT.md
BAT_COST0 = 95.0  # EUR per MWh, CONTRACT.md stored-cost rule
BAT_SOC0 = 0.40  # plant-manual.md: the battery starts the run at about 40 percent
DEADBAND_HZ = 0.12  # README.md logging deadband of the frequency recorder
# genset-datasheet.md: efficiency (electrical output over fuel input) against load fraction
ETA_TABLE = ((0.2, 0.2823), (0.3, 0.3194), (0.4, 0.3495), (0.5, 0.3726), (0.6, 0.3887),
             (0.7, 0.3978), (0.8, 0.3999), (0.9, 0.3950), (1.0, 0.3831))
TIE_OPEN0 = 62  # Annex C
DR_EVENT0 = (11, 14)  # Annex C: the first demand-response event; the group is named in Annex C


def eta(x: float) -> float:
    """Linear interpolation of the datasheet efficiency table."""
    pts = ETA_TABLE
    if x <= pts[0][0]:
        return pts[0][1]
    for (a, ea), (b, eb) in zip(pts, pts[1:]):
        if x <= b:
            return ea + (eb - ea) * (x - a) / (b - a)
    return pts[-1][1]


def tariff(hour: float) -> float:
    """Annex B import tariff by plant hour, EUR per MWh."""
    h = int(hour)
    if 46 <= h < 62:
        return 58.0
    c = h % 24
    return 110.0 if c < 6 else 125.0 if c < 10 else 105.0 if c < 16 else 210.0 if c < 22 else 125.0
