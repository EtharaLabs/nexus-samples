"""Window design arithmetic shared by the simulator's hidden threshold and the planners.

``window_need`` is a pure function of a parameter dictionary and an hourly ambient forecast. The
simulator evaluates it once on the true parameters to place the hidden far-loop hunt threshold;
a planner evaluates it on its own estimates.
"""

from __future__ import annotations

from .params import (
    C_W,
    DESIGN_DT,
    EPS_HX,
    FAR,
    NEAR,
    RHO_FAR,
    RHO_NEAR,
    SECONDARY_SLOPE,
    SUPPLY_LOSS_COEFF,
)

V_FAR = 600000.0
WINDOW_HOURS = range(66, 72)


def indoor(k: int, decoy: int, clock: float) -> float:
    if k == decoy:
        start, end, low = 0.5, 6.5, 12.0
    else:
        start, end, low = 22.0, 6.0, 18.0
    inside = (start <= clock < end) if start < end else (clock >= start or clock < end)
    return low if inside else 20.0


def load(K: dict, fc: list, h: int, k: int) -> float:
    return K["UA"][k] * max(0.0, indoor(k, K["decoy"], (h + 0.5) % 24.0) - fc[h])


def tsec(K: dict, k: int, lk: float) -> float:
    return K["Tsec0"][k] + SECONDARY_SLOPE * lk / (K["UA"][k] * DESIGN_DT)


def far_tau(q_sat: float) -> float:
    return min(3.0, max(1.0, V_FAR / q_sat / 3600.0))


def supply_for(
    K: dict, fc: list, q_sat: float | None, near_margin: float = 1.0
) -> dict:
    """Lowest supply temperature that keeps the near floor and, when q_sat is given, the far heat."""
    ta_nf = 0.0
    ta_sat = 0.0
    for h in WINDOW_HOURS:
        for k in NEAR:
            lk = load(K, fc, h, k)
            ts = tsec(K, k, lk)
            ta_nf = max(ta_nf, ts + (55.0 + near_margin - ts) / RHO_NEAR + 0.3)
        if q_sat is not None:
            lf = sum(load(K, fc, h, k) for k in FAR)
            tsf = (
                sum(load(K, fc, h, k) * tsec(K, k, load(K, fc, h, k)) for k in FAR) / lf
            )
            ta = tsf + lf / (EPS_HX * C_W * q_sat)
            tau = far_tau(q_sat)
            ta_sat = max(
                ta_sat,
                (ta - SUPPLY_LOSS_COEFF * 8.0 * tau) / (1.0 - SUPPLY_LOSS_COEFF * tau),
            )
    return {"ta_nf": ta_nf, "ta_sat": ta_sat}


def flow_need(K: dict, fc: list, ts_w: float, q_sat: float | None) -> float:
    """Largest hourly pump flow the window needs at supply ``ts_w`` (kg/s)."""
    need = 0.0
    tau = far_tau(q_sat if q_sat else 110.0)
    taf = ts_w - SUPPLY_LOSS_COEFF * (ts_w - 8.0) * tau
    tan = ts_w - SUPPLY_LOSS_COEFF * (ts_w - 8.0) * 0.2
    for h in WINDOW_HOURS:
        qn = 0.0
        for k in NEAR:
            lk = load(K, fc, h, k)
            qn += lk / (C_W * (1.0 - RHO_NEAR) * (tan - tsec(K, k, lk)))
        qf = 0.0
        for k in FAR:
            lk = load(K, fc, h, k)
            qf += lk / (C_W * (1.0 - RHO_FAR) * (taf - tsec(K, k, lk)))
        if q_sat is not None:
            qf = min(qf, q_sat)
        need = max(need, qn + qf)
    return need


REFERENCE_TS_MARGIN = 2.0


def reference_need(K: dict, fc: list) -> tuple[float, float]:
    s = supply_for(K, fc, K["q_sat"])
    ts_w = max(s["ta_nf"], s["ta_sat"]) + REFERENCE_TS_MARGIN
    return ts_w, flow_need(K, fc, ts_w, K["q_sat"])
