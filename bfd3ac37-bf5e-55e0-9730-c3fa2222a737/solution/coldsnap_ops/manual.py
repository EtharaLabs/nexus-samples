"""Values and formulas an operator reads from the shipped documents (CONTRACT.md, README.md, the
plant manual, and the pump datasheet). Nothing here comes from the simulator's code."""

from __future__ import annotations

C_W = 4.19e-3  # MW per (kg/s K), manual "Units"
SUBSTATIONS = ("S1", "S2", "S3", "S4", "S5", "S6")
NEAR = (0, 1, 2)
FAR = (3, 4, 5)

# Plant manual, "Parameter ranges" (operators plan on the middle of each range)
UA = [0.120, 0.120, 0.120, 0.130, 0.130, 0.130]  # MW/K
TSEC0 = [33.0, 33.0, 33.0, 46.0, 46.0, 46.0]  # C
BOILER_CAP = {"B1": 7.6, "B2": 8.8, "B3": 7.6}  # MW
TANK_MWH = 120.0
TANK_STATIC_HEAD = 1.575  # bar at a full tank
PUMP_RATED_FLOW = 310.0  # kg/s at speed 1.0, middle of 250-370

# Plant manual, "Substations" and "Network"
SECONDARY_SLOPE = 12.0
DESIGN_DT = 40.0
EPS_HX = 0.92
RHO_NEAR = 0.35
RHO_FAR = 0.35
SUPPLY_LOSS = 0.012  # K per K of (supply - 8 C) per hour of transport
FAR_LINE_KG = 600000.0
NEAR_TRANSPORT_H = 0.2

# Plant manual, "Boilers": condensing note for B1 and B3
LAMBDA = {"B1": 1.08, "B2": 1.20, "B3": 1.10}


def dew_point(boiler: str) -> float:
    return 68.0 - 40.0 * (LAMBDA[boiler] - 1.0)


# Pump datasheet
P_ATM = 1.013
SUCTION_LOSS = 0.30


def npshr(speed: float) -> float:
    return 0.15 + 1.9 * speed**8


VAPOUR = (
    (40.0, 0.0738),
    (45.0, 0.0959),
    (50.0, 0.1235),
    (55.0, 0.1576),
    (60.0, 0.1994),
    (65.0, 0.2503),
    (70.0, 0.3119),
    (75.0, 0.3858),
    (80.0, 0.4739),
)


def vapour_pressure(t: float) -> float:
    if t <= VAPOUR[0][0]:
        return VAPOUR[0][1]
    for (t0, p0), (t1, p1) in zip(VAPOUR, VAPOUR[1:]):
        if t <= t1:
            return p0 + (p1 - p0) * (t - t0) / (t1 - t0)
    return VAPOUR[-1][1]


# CONTRACT.md and its annexes
CONTRACTED_MWH = 144.0
COST_CAP = 57.1
MAX_CHANGES = 40


# Annex A: (start clock hour, end clock hour, setback indoor C) per substation
ANNEX_A = [
    (22.0, 6.0, 18.0),
    (22.0, 6.0, 18.0),
    (0.5, 6.5, 12.0),
    (22.0, 6.0, 18.0),
    (22.0, 6.0, 18.0),
    (22.0, 6.0, 18.0),
]
DEEP_SETBACK = 2  # the only Annex A schedule below 15 C


def indoor(k: int, clock: float) -> float:
    start, end, low = ANNEX_A[k]
    inside = (start <= clock < end) if start < end else (clock >= start or clock < end)
    return low if inside else 20.0


def tariff(hour: int) -> float:
    clock = hour % 24
    if clock < 6:
        return 28.0
    if clock < 16:
        return 46.0
    if clock < 23:
        return 74.0
    return 46.0
