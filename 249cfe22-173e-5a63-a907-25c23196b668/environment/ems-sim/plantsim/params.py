"""Seeded plant parameters for the island microgrid.

Every documented parameter is drawn inside the range the plant manual states. Hidden dynamics and
revision hours draw their own parameters here; none is documented as a finding.
"""

from __future__ import annotations

import random

STEP_S = 10
SUB = 10  # raw samples per simulation step (1-second raw resolution)
HOURS = 72
SPH = 360  # steps per plant hour
N_STEPS = HOURS * SPH
WINDOW_START = 66 * SPH

GROUPS = ("HOSP", "WATER", "TELCO", "MILL", "TOWN", "DOCK")
CRIT0 = ("HOSP", "WATER", "TELCO")
# peak demand (MW) of each load group; the daily shape is in model.py
PEAK = {"HOSP": 0.70, "WATER": 0.60, "TELCO": 0.32, "MILL": 1.45, "TOWN": 1.05, "DOCK": 0.80}

RANGES = {
    "g_rated": (3.0, 3.0),  # documented, MW each
    "pmin": (1.35, 1.55),  # NOT documented; the seeded minimum stable load, MW (both gensets)
    "bat_cap": (11.6, 12.4),  # MWh
    "bat_inv": (2.4, 2.6),  # MW inverter rating
    "pv_peak": (1.9, 2.1),  # MW
    "droop": (0.038, 0.042),  # per unit
    "bat_soc0": (0.38, 0.42),
}

BAND = (49.5, 50.5)  # Hz, CONTRACT.md band
DEADBAND_HZ = 0.12  # README.md logging deadband of the frequency recorder


def _u(rng: random.Random, lo: float, hi: float) -> float:
    return lo + (hi - lo) * rng.random()


def draw(seed: int) -> dict:
    rng = random.Random(seed)
    r = RANGES
    p: dict = {"seed": seed}
    p["g_rated"] = 3.0
    p["pmin"] = _u(rng, *r["pmin"])
    p["bat_cap"] = _u(rng, *r["bat_cap"])
    p["bat_inv"] = _u(rng, *r["bat_inv"])
    p["pv_peak"] = _u(rng, *r["pv_peak"])
    p["droop"] = _u(rng, *r["droop"])
    p["soc0"] = _u(rng, *r["bat_soc0"])
    p["load_scale"] = {g: _u(rng, 0.995, 1.005) for g in GROUPS}
    # hidden R1: inverter thermal derate above this discharge power (MW)
    p["p_derate"] = _u(rng, 1.35, 1.55)
    p["derate_gain"] = _u(rng, 2.6, 3.2)  # sag fraction per MW above the knee
    p["derate_period_s"] = _u(rng, 420.0, 540.0)
    # hidden R2: genset-bus hunt amplitude Hz per MW below pmin
    p["hunt_k"] = _u(rng, 1.6, 2.0)
    p["hunt_period_s"] = _u(rng, 24.0, 32.0)
    # forecast timing errors, plant hours (1 to 3)
    p["pv_shift_h"] = rng.choice((-1, 1)) * _u(rng, 1.0, 3.0)
    p["load_shift_h"] = rng.choice((-1, 1)) * _u(rng, 1.0, 3.0)
    p["pv_cloud"] = [_u(rng, 0.85, 1.0) for _ in range(4)]
    # faults
    p["gens"] = ["G1", "G2"]
    fg = rng.choice((0, 1))
    p["fault_gen"] = fg
    p["h_dip"] = _u(rng, 11.0, 15.0)  # PV ramp that coincides with the governor fault
    p["h_gov"] = p["h_dip"] + _u(rng, 0.5, 1.5)
    p["gov_eta_loss"] = _u(rng, 0.20, 0.26)  # fuel-to-power balance degrades after the fault
    order = list(range(len(GROUPS)))
    rng.shuffle(order)
    p["dr_group"] = "DOCK"  # fixed by CONTRACT.md Annex C
    meters = ["PM-" + g for g in GROUPS]
    others = [i for i in range(len(GROUPS)) if GROUPS[i] != p["dr_group"]]
    rng.shuffle(others)
    p["bias_tag"] = "PM-" + GROUPS[others[0]]
    p["bias_factor"] = rng.choice((_u(rng, 1.10, 1.14), _u(rng, 0.86, 0.90)))
    p["drift_tag"] = "PM-" + GROUPS[others[1]]
    p["h_drift"] = _u(rng, 29.0, 31.0)
    p["drift_rate"] = rng.choice((1.0, -1.0)) * _u(rng, 0.007, 0.010)
    p["unit_tag"] = "PM-" + GROUPS[others[2]]
    p["h_unit"] = _u(rng, 39.6, 40.4)
    p["replay_rtu"] = "RTU-" + GROUPS[others[3]]
    p["h_replay"] = _u(rng, 23.5, 24.5)
    # steerability: three revisions, hours drawn per seed. The draw is repeated until a block of
    # cheap import hours free of the demand-response penalty lies between hour 46 and the revised
    # tie-open hour, so a plan that reads the channel always has somewhere to charge.
    while True:
        p["h_out0"] = 62
        p["h_out1"] = float(rng.choice((54, 55, 56, 57, 58)))
        p["rv_out_issue"] = float(int(_u(rng, 36.0, min(44.0, p["h_out1"] - 6.0) + 0.99)))
        p["dr_start"] = float(int(_u(rng, 46.0, 52.99)))  # last Annex C event start (whole hour)
        p["dr_len"] = 2
        p["dr_ext"] = float(rng.choice((2, 3, 4)))
        p["rv_dr_issue"] = float(int(_u(rng, 30.0, min(46.0, p["dr_start"] - 4.0) + 0.99)))
        lo, hi = 46.1, p["h_out1"] - 0.4
        free = max(0.0, hi - lo) - max(0.0, min(hi, p["dr_start"] + p["dr_len"] + p["dr_ext"]) - max(lo, p["dr_start"]))
        if free >= 3.8:
            break
    p["rv_crit_issue"] = float(int(_u(rng, 40.0, 58.99)))
    p["rv_crit_eff"] = float(rng.choice((67, 68, 69, 70)))
    p["crit_in"] = rng.choice(("MILL", "TOWN"))
    p["crit_out"] = rng.choice(("WATER", "TELCO"))
    p["noise_seed"] = rng.getrandbits(64)
    return p
