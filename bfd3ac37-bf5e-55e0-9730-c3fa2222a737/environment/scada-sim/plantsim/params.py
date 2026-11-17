"""Seeded plant parameters.

Every documented parameter is drawn inside the range the plant manual states. Hidden dynamics
draw their own parameters here; none of them is documented as a finding anywhere the agent can
read.
"""

from __future__ import annotations

import random

C_W = 4.19e-3  # MW per (kg/s * K)
STEP_S = 10
STEPS_PER_HOUR = 360
HOURS = 72
N_STEPS = HOURS * STEPS_PER_HOUR
WINDOW_START = 66 * STEPS_PER_HOUR
P_ATM = 1.013  # bar, the datasheet's atmospheric pressure

SUBSTATIONS = ("S1", "S2", "S3", "S4", "S5", "S6")
NEAR = (0, 1, 2)
FAR = (3, 4, 5)
BOILERS = ("B1", "B2", "B3")

# Documented ranges (plant manual section "Parameter ranges").
RANGES = {
    "pump_rated_flow": (250.0, 370.0),  # kg/s at speed 1.0
    "ua_near": (0.1194, 0.1206),  # MW/K per near substation
    "ua_far": (0.1294, 0.1306),  # MW/K per far substation
    "tsec0_near": (32.7, 33.3),  # C, secondary return at zero load
    "tsec0_far": (45.7, 46.3),
    "tank_capacity": (118.0, 122.0),  # MWh
    "boiler_capacity_b1": (7.5, 7.7),  # MW
    "boiler_capacity_b2": (8.7, 8.9),
    "boiler_capacity_b3": (7.5, 7.7),
    "tank_static_head": (1.55, 1.60),  # bar at full tank
    "cold_snap_low": (-15.15, -14.85),  # C, forecast floor of the cold snap
}

SECONDARY_SLOPE = 12.0  # K rise of secondary return from zero to design load
DESIGN_DT = 40.0  # K, design indoor-outdoor difference
EPS_HX = 0.92  # substation exchanger effectiveness (manual)
RHO_NEAR = 0.35  # substation controllers' return fraction (manual)
RHO_FAR = 0.35
SUCTION_LOSS = 0.30  # bar at speed 1.0 (datasheet)
NPSHR_COEFF = 1.90  # datasheet curve NPSHr = 0.15 + coeff * speed^8, bar
TANK_LOSS_PER_H = 0.002
TANK_MAX_RATE = 14.0  # MW charge or discharge (manual)
SUPPLY_LOSS_COEFF = (
    0.012  # K per K of (supply - 8 C) on the far branch per hour of transport
)
DEW_POINT_A = 68.0
DEW_POINT_B = 40.0
LAMBDA = {"B1": 1.08, "B2": 1.20, "B3": 1.10}  # excess-air ratio per boiler (manual)


def _u(rng: random.Random, lo: float, hi: float) -> float:
    return lo + (hi - lo) * rng.random()


def draw(seed: int) -> dict:
    rng = random.Random(seed)
    p: dict = {"seed": seed}
    r = RANGES
    p["Qnom"] = _u(rng, *r["pump_rated_flow"])
    p["UA"] = [_u(rng, *r["ua_near"]) for _ in NEAR] + [
        _u(rng, *r["ua_far"]) for _ in FAR
    ]
    p["Tsec0"] = [_u(rng, *r["tsec0_near"]) for _ in NEAR] + [
        _u(rng, *r["tsec0_far"]) for _ in FAR
    ]
    p["E_tank"] = _u(rng, *r["tank_capacity"])
    p["cap"] = [
        _u(rng, *r["boiler_capacity_b1"]),
        _u(rng, *r["boiler_capacity_b2"]),
        _u(rng, *r["boiler_capacity_b3"]),
    ]
    p["p_static"] = _u(rng, *r["tank_static_head"])
    p["T_cold"] = _u(rng, *r["cold_snap_low"])
    # weather
    p["T_mild"] = _u(rng, 4.3, 4.7)
    p["h_cold"] = _u(rng, 59.4, 59.6)  # onset of the cold-snap descent
    p["h_dip"] = _u(rng, 11.0, 15.0)  # pre-front dip that coincides with the B2 fault
    p["fc_err"] = [_u(rng, -0.3, 0.3) for _ in range(HOURS + 1)]
    # boilers: base efficiency at full load, condensing gain per K below the dew point
    p["eta0"] = [_u(rng, 0.878, 0.882), _u(rng, 0.928, 0.932), _u(rng, 0.878, 0.882)]
    p["cond_gain"] = [_u(rng, 0.0295, 0.0305), 0.0, _u(rng, 0.0295, 0.0305)]
    # R5: B2 degrades after its logged fault code
    p["h_b2fault"] = p["h_dip"] + _u(rng, 0.5, 1.5)
    p["b2_eta_after"] = _u(rng, 0.70, 0.73)
    # R2/R7: far-branch valve saturation flow (kg/s)
    p["q_sat"] = _u(rng, 104.0, 116.0)
    # R7: the branch valve is fully open before the branch flow reaches its limit; the last
    # part of the rise comes from substation valves the far RTU does not watch
    p["valve_full_frac"] = _u(rng, 0.93, 0.95)
    # R1: pump-flow threshold of the far-loop hunt, as a multiple of the reference need
    p["osc_factor"] = _u(rng, 1.026, 1.032)
    p["osc_gain"] = _u(rng, 550.0, 650.0)  # K per unit of relative exceedance
    p["osc_period_s"] = _u(rng, 330.0, 390.0)
    p["osc_phase"] = _u(rng, 0.0, 6.283185307179586)
    # Faults on sensors and RTUs, each on a distinct substation where it matters.
    order = list(range(6))
    rng.shuffle(order)
    p["decoy"] = 2  # S3, the deep night setback of CONTRACT.md Annex A (a static document)
    others = [k for k in order if k != p["decoy"]]
    p["bias_sub"] = others[0]
    p["bias_factor"] = rng.choice((_u(rng, 1.10, 1.14), _u(rng, 0.86, 0.90)))
    p["drift_sub"] = others[1]
    p["h_drift"] = _u(rng, 29.0, 31.0)
    p["drift_rate"] = rng.choice((1.0, -1.0)) * _u(
        rng, 0.007, 0.010
    )  # fraction per hour
    p["unit_sub"] = others[2]
    p["h_unit"] = _u(rng, 39.6, 40.4)
    p["replay_sub"] = others[3]
    p["h_replay"] = _u(rng, 23.5, 24.5)
    p["replay_back_h"] = _u(rng, 2.0, 2.0)
    p["noise_seed"] = rng.getrandbits(64)
    return p
