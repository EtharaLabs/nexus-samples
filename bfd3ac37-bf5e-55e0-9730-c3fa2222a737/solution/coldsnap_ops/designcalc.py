"""Window design from the manual's substation and network formulas and the operator's estimates."""

from __future__ import annotations

from . import manual as M

WINDOW_HOURS = range(66, 72)


def load(fc: list[float], h: int, k: int) -> float:
    return M.UA[k] * max(0.0, M.indoor(k, (h + 0.5) % 24.0) - fc[h])


def tsec(k: int, lk: float) -> float:
    return M.TSEC0[k] + M.SECONDARY_SLOPE * lk / (M.UA[k] * M.DESIGN_DT)


def far_tau(q: float) -> float:
    return min(3.0, max(1.0, M.FAR_LINE_KG / q / 3600.0))


def supply_for(fc: list[float], q_sat: float | None, near_margin: float = 1.0) -> float:
    """Lowest supply temperature holding the near floor and, when q_sat is known, the far heat."""
    best = 0.0
    for h in WINDOW_HOURS:
        for k in M.NEAR:
            lk = load(fc, h, k)
            ts = tsec(k, lk)
            best = max(best, ts + (55.0 + near_margin - ts) / M.RHO_NEAR + 0.3)
        if q_sat is not None:
            lf = sum(load(fc, h, k) for k in M.FAR)
            tsf = sum(load(fc, h, k) * tsec(k, load(fc, h, k)) for k in M.FAR) / lf
            ta = tsf + lf / (M.EPS_HX * M.C_W * q_sat)
            tau = far_tau(q_sat)
            best = max(
                best, (ta - M.SUPPLY_LOSS * 8.0 * tau) / (1.0 - M.SUPPLY_LOSS * tau)
            )
    return best


def _far_flow(fc: list[float], h: int, taf: float) -> float:
    total = 0.0
    for k in M.FAR:
        lk = load(fc, h, k)
        total += lk / (M.C_W * (1.0 - M.RHO_FAR) * (taf - tsec(k, lk)))
    return total


def flow_need(fc: list[float], ts_w: float, q_sat: float | None) -> float:
    """With a measured saturation flow the far line runs at q_sat and its transport delay follows from
    it; without one the delay is the manual's 600 t divided by the far-branch flow the hour calls
    for, solved to a fixed point.
    """
    need = 0.0
    tan = ts_w - M.SUPPLY_LOSS * (ts_w - 8.0) * M.NEAR_TRANSPORT_H
    for h in WINDOW_HOURS:
        qn = 0.0
        for k in M.NEAR:
            lk = load(fc, h, k)
            qn += lk / (M.C_W * (1.0 - M.RHO_NEAR) * (tan - tsec(k, lk)))
        if q_sat is not None:
            taf = ts_w - M.SUPPLY_LOSS * (ts_w - 8.0) * far_tau(q_sat)
            qf = min(_far_flow(fc, h, taf), q_sat)
        else:
            tau = 1.0
            for _ in range(20):
                taf = ts_w - M.SUPPLY_LOSS * (ts_w - 8.0) * tau
                qf = _far_flow(fc, h, taf)
                tau = far_tau(max(qf, 1.0))
        need = max(need, qn + qf)
    return need


def window_heat(fc: list[float]) -> float:
    """Forecast customer heat demand over hours 66 to 72 (MWh)."""
    return sum(load(fc, h, k) for h in WINDOW_HOURS for k in range(6))


def tank_floor(speed: float, return_c: float = 58.0) -> float:
    """Lowest tank level fraction that keeps NPSH margin at ``speed`` (datasheet, absolute pressure)."""
    need = (
        M.npshr(speed)
        + M.SUCTION_LOSS * speed * speed
        + M.vapour_pressure(return_c)
        - M.P_ATM
    )
    return max(0.05, need / M.TANK_STATIC_HEAD + 0.06)
