"""Deterministic district-heating plant simulator, 10-second resolution, 72 simulated hours.

The same code runs paced (the live trial), unpaced (build-time seed admission and the collect
step's replay), and in-process (build proofs). A run is a pure function of (seed, action log): the action log
records each accepted control change at the step index at which it took effect.
"""

from __future__ import annotations

import random

from . import design, detmath
from .params import (
    BOILERS,
    C_W,
    DEW_POINT_A,
    DEW_POINT_B,
    DESIGN_DT,
    EPS_HX,
    FAR,
    HOURS,
    LAMBDA,
    N_STEPS,
    NEAR,
    NPSHR_COEFF,
    P_ATM,
    RHO_FAR,
    RHO_NEAR,
    SECONDARY_SLOPE,
    STEP_S,
    STEPS_PER_HOUR,
    SUBSTATIONS,
    SUCTION_LOSS,
    SUPPLY_LOSS_COEFF,
    TANK_LOSS_PER_H,
    TANK_MAX_RATE,
    WINDOW_START,
    draw,
)

DT_H = STEP_S / 3600.0
RAMP_STEPS = 120  # 20 simulated minutes
FLOOR_C = 55.0
V_FAR = 600000.0  # kg of water in the far branch supply line
NEAR_TRANSPORT_H = 0.2
RETURN_LAG_STEPS = 18.0
RETURN_LOSS_K = 1.5
VALVE_RATE = 0.01  # fraction of stroke per 10-second step
LN_RANGEABILITY = 3.912023005428146  # ln 50
INITIAL = {
    "supply_temp": 90.0,
    "pump_speed": 0.70,
    "boilers": ["B2", "B1", "B3"],
    "tank_rate": 0.0,
}
INITIAL_TANK_LEVEL = 0.40
LIMITS = {
    "supply_temp": (60.0, 120.0),
    "pump_speed": (0.30, 1.00),
    "tank_rate": (-TANK_MAX_RATE, TANK_MAX_RATE),
}
CONTRACTED_MWH = 144.0
COST_CAP = 57.1  # EUR per MWh of heat delivered in hours 66 to 72


def tariff(hour_index: int) -> float:
    """Annex B: EUR per MWh of fuel for plant hour ``hour_index`` (hour 0 starts at 00:00)."""
    clock = hour_index % 24
    if clock < 6:
        return 28.0
    if clock < 16:
        return 46.0
    if clock < 23:
        return 74.0
    return 46.0


def vapour_pressure(t_c: float) -> float:
    """Datasheet table, bar, linear between rows."""
    table = (
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
    if t_c <= table[0][0]:
        return table[0][1]
    for (t0, p0), (t1, p1) in zip(table, table[1:]):
        if t_c <= t1:
            return p0 + (p1 - p0) * (t_c - t0) / (t1 - t0)
    return table[-1][1]


def npshr(speed: float) -> float:
    """Datasheet NPSH-required curve, bar: 0.15 + 1.9 * speed**8."""
    s2 = speed * speed
    s4 = s2 * s2
    return 0.15 + NPSHR_COEFF * s4 * s4


def setback_schedule(k: int, decoy: int) -> tuple[float, float, float]:
    """Annex A: (start clock hour, end clock hour, setback indoor C) of substation k."""
    if k == decoy:
        return (0.5, 6.5, 12.0)
    return (22.0, 6.0, 18.0)


def indoor(k: int, decoy: int, clock: float) -> float:
    start, end, low = setback_schedule(k, decoy)
    if start < end:
        inside = start <= clock < end
    else:
        inside = clock >= start or clock < end
    return low if inside else 20.0


def ambient_true(p: dict, hour: float) -> float:
    clock = hour % 24.0
    diurnal = 3.0 * detmath.sin(6.283185307179586 * (clock - 9.0) / 24.0)
    t = p["T_mild"] + diurnal
    d0 = p["h_dip"]
    if d0 <= hour < d0 + 12.0:
        x = hour - d0
        t -= 3.0 * (x / 4.0 if x < 4.0 else (12.0 - x) / 8.0)
    h0 = p["h_cold"]
    if hour >= h0:
        x = min(1.0, (hour - h0) / 7.0)
        cold = p["T_cold"] + 1.0 * detmath.sin(6.283185307179586 * (clock - 9.0) / 24.0)
        t = (1.0 - x) * t + x * cold
    return t


def forecast(p: dict) -> list[float]:
    """Hourly forecast for plant hours 0..72: the true hourly mean plus a small seeded error."""
    out = []
    for h in range(HOURS + 1):
        out.append(round(ambient_true(p, h + 0.5) + p["fc_err"][h], 1))
    return out


def osc_threshold(p: dict) -> float:
    """R1: the pump flow above which the far loop hunts (kg/s)."""
    _, need = design.reference_need(p, forecast(p))
    return p["osc_factor"] * need


class ControlError(Exception):
    pass


class Plant:
    """One trial's plant. ``advance_to(step)`` integrates; ``request`` applies a control change."""

    def __init__(self, seed: int, observer=None):
        self.p = draw(seed)
        self.seed = seed
        self.step_index = 0
        p = self.p
        self.q_osc = osc_threshold(p)
        self.amb = [
            ambient_true(p, i / STEPS_PER_HOUR) for i in range(0, N_STEPS + 1, 6)
        ]
        self.target = dict(INITIAL)
        self.target["boilers"] = list(INITIAL["boilers"])
        self.start_vals = dict(self.target)
        self.ramp_start = -RAMP_STEPS
        self.cur = {
            k: self.target[k] for k in ("supply_temp", "pump_speed", "tank_rate")
        }
        self.boilers = list(self.target["boilers"])
        self.tank_e = INITIAL_TANK_LEVEL * p["E_tank"]
        self.tank_cost = self.tank_e * 30.0
        self.ts_hist: list[float] = []
        self.tr_lag = [55.0] * 6
        self.tpr_smooth = 55.0
        self.cavitating = False
        self.u_valve = -1.0  # far-branch valve position, set on the first step
        self.accepted = 0
        self.rejected = 0
        self.actions: list[dict] = []
        self.rejections: list[dict] = []
        self.control_log: list[dict] = []
        self.rng = random.Random(p["noise_seed"])
        # graded window accumulators
        self.win_heat = 0.0
        self.win_heat_k = [0.0] * 6
        self.win_cost = 0.0
        self.win_below = [0] * 6
        self.win_min_return = [999.0] * 6
        self.win_demand = 0.0
        self.observer = observer
        self.events: list[dict] = []
        self.b2_fault_logged = False
        self.unit_logged = False

    # ------------------------------------------------------------------ controls
    def in_ramp(self) -> bool:
        return self.step_index - self.ramp_start < RAMP_STEPS

    def request(self, change: dict) -> dict:
        """Apply one control request at the current step. Raises ControlError when invalid."""
        clean = validate(change)
        if self.step_index >= WINDOW_START or self.in_ramp():
            self.rejected += 1
            entry = {
                "step": self.step_index,
                "change": clean,
                "reason": "window" if self.step_index >= WINDOW_START else "ramp",
            }
            self.rejections.append(entry)
            self.control_log.append(
                {"step": self.step_index, "change": clean, "accepted": False}
            )
            self.events.append(
                {
                    "step": self.step_index,
                    "source": "SCADA",
                    "event": "control_rejected",
                    "reason": entry["reason"],
                    "change": clean,
                }
            )
            return {"accepted": False, "reason": entry["reason"]}
        self._apply(clean)
        self.accepted += 1
        self.actions.append({"step": self.step_index, "change": clean})
        self.control_log.append(
            {"step": self.step_index, "change": clean, "accepted": True}
        )
        self.events.append(
            {
                "step": self.step_index,
                "source": "SCADA",
                "event": "control_change",
                "change": clean,
            }
        )
        return {"accepted": True}

    def _apply(self, clean: dict) -> None:
        self.start_vals = {
            k: self.cur[k] for k in ("supply_temp", "pump_speed", "tank_rate")
        }
        for key, value in clean.items():
            if key == "boilers":
                for b in BOILERS:
                    was, now = b in self.boilers, b in value
                    if was != now:
                        self.events.append(
                            {
                                "step": self.step_index,
                                "source": "RTU-BLR",
                                "event": "boiler_start" if now else "boiler_stop",
                                "subject": b,
                            }
                        )
                self.target["boilers"] = list(value)
                self.boilers = list(value)
            else:
                self.target[key] = value
        self.ramp_start = self.step_index

    # ------------------------------------------------------------------ physics
    def advance_to(self, step: int) -> None:
        step = min(step, N_STEPS)
        while self.step_index < step:
            self._step()

    def _step(self) -> None:
        p = self.p
        i = self.step_index
        hour = i / STEPS_PER_HOUR
        clock = hour % 24.0
        # ramp
        frac = (i - self.ramp_start) / RAMP_STEPS
        if frac >= 1.0:
            for key in ("supply_temp", "pump_speed", "tank_rate"):
                self.cur[key] = self.target[key]
        else:
            for key in ("supply_temp", "pump_speed", "tank_rate"):
                a = self.start_vals[key]
                self.cur[key] = a + (self.target[key] - a) * frac
        ts_set = self.cur["supply_temp"]
        speed = self.cur["pump_speed"]
        t_amb = self.amb[i // 6]
        # pump suction and cavitation (R8)
        level = self.tank_e / p["E_tank"]
        p_in = p["p_static"] * level - SUCTION_LOSS * speed * speed
        margin = (p_in + P_ATM) - (npshr(speed) + vapour_pressure(self.tpr_smooth))
        if self.cavitating:
            if margin > 0.05:
                self.cavitating = False
        elif margin < 0.0:
            self.cavitating = True
        if self.cavitating:
            kappa = 0.30 + 0.12 * detmath.sin(6.283185307179586 * i * STEP_S / 140.0)
        else:
            kappa = 1.0
        q_pump = p["Qnom"] * speed * kappa
        # arriving supply temperatures
        ts_prev = self.ts_hist[-1] if self.ts_hist else ts_set
        loads = [0.0] * 6
        tsec = [0.0] * 6
        wants = [0.0] * 6
        ta = [0.0] * 6
        rho = [0.0] * 6
        q_far_prev = getattr(self, "_q_far_prev", 60.0)
        tau_near = int(NEAR_TRANSPORT_H * STEPS_PER_HOUR)
        tau_far_h = min(3.0, max(1.0, V_FAR / max(q_far_prev, 1.0) / 3600.0))
        tau_far = int(tau_far_h * STEPS_PER_HOUR)
        n = len(self.ts_hist)
        t_near = (
            self.ts_hist[n - tau_near]
            if n >= tau_near and tau_near > 0
            else (self.ts_hist[0] if n else ts_prev)
        )
        t_far = (
            self.ts_hist[n - tau_far]
            if n >= tau_far
            else (self.ts_hist[0] if n else ts_prev)
        )
        t_far -= SUPPLY_LOSS_COEFF * (t_far - 8.0) * tau_far_h
        t_near -= SUPPLY_LOSS_COEFF * (t_near - 8.0) * 0.2
        for k in range(6):
            tin = indoor(k, p["decoy"], clock)
            load = p["UA"][k] * max(0.0, tin - t_amb)
            loads[k] = load
            tsec[k] = p["Tsec0"][k] + SECONDARY_SLOPE * load / (p["UA"][k] * DESIGN_DT)
            ta[k] = t_near if k in NEAR else t_far
            rho[k] = RHO_NEAR if k in NEAR else RHO_FAR
            gap = (1.0 - rho[k]) * (ta[k] - tsec[k])
            wants[k] = load / (C_W * gap) if gap > 1.0 else load / C_W
        # hydraulics: near branch has priority, far branch limited by valve saturation (R2)
        q = [0.0] * 6
        near_want = wants[0] + wants[1] + wants[2]
        far_want = wants[3] + wants[4] + wants[5]
        # far-branch valve: equal-percentage, fully open at valve_full_frac * q_sat, stroke rate
        # limited; past full open the substation valves carry the flow on up to q_sat
        full = p["valve_full_frac"] * p["q_sat"]
        ratio = min(1.0, far_want / full)
        u_target = max(0.0, 1.0 + detmath.log(max(ratio, 1e-6)) / LN_RANGEABILITY)
        if self.u_valve < 0.0:
            self.u_valve = u_target
        else:
            self.u_valve += max(-VALVE_RATE, min(VALVE_RATE, u_target - self.u_valve))
        if self.u_valve >= 1.0 - 1e-12:
            valve_cap = p["q_sat"]
        else:
            valve_cap = full * detmath.exp((self.u_valve - 1.0) * LN_RANGEABILITY)
        # the near branch sits closest to the pump and draws first; the far branch takes what is left
        near_share = min(1.0, q_pump / near_want) if near_want > 0.0 else 1.0
        for k in NEAR:
            q[k] = wants[k] * near_share
        avail = min(valve_cap, max(0.0, q_pump - near_want * near_share))
        far_scale = min(1.0, avail / far_want) if far_want > 0.0 else 0.0
        for k in FAR:
            q[k] = wants[k] * far_scale
        q_near = q[0] + q[1] + q[2]
        q_far = q[3] + q[4] + q[5]
        bypass = max(0.0, q_pump - q_near - q_far)
        self._q_near_prev = q_near
        self._q_far_prev = q_far
        # substations
        heat = [0.0] * 6
        tr_act = [0.0] * 6
        osc = 0.0
        if q_pump > self.q_osc:
            # hard onset: the loop jumps into a finite limit cycle once the threshold is crossed
            osc = min(16.0, 10.0 + p["osc_gain"] * (q_pump / self.q_osc - 1.0))
        for k in range(6):
            load = loads[k]
            if q[k] >= wants[k] * 0.999:
                h = load
                tr = tsec[k] + rho[k] * (ta[k] - tsec[k])
            elif q[k] > 0.15 * wants[k]:
                h = min(load, EPS_HX * C_W * q[k] * (ta[k] - tsec[k]))
                tr = ta[k] - h / (C_W * q[k])
            else:
                h = EPS_HX * C_W * q[k] * max(0.0, ta[k] - tsec[k])
                h = min(h, load)
                tr = 30.0
            heat[k] = h
            self.tr_lag[k] += (tr - self.tr_lag[k]) / RETURN_LAG_STEPS
            value = self.tr_lag[k]
            if k in FAR and osc > 0.0:
                value += osc * detmath.sin(
                    6.283185307179586 * i * STEP_S / p["osc_period_s"]
                    + p["osc_phase"]
                    + k
                )
            tr_act[k] = value
        # plant return
        if q_pump > 1e-6:
            # the far-loop hunt is local: the long return line smooths it before the plant
            mix = sum(q[k] * self.tr_lag[k] for k in range(6)) + bypass * ts_prev
            t_pr = mix / (q_near + q_far + bypass) - RETURN_LOSS_K
        else:
            t_pr = self.tpr_smooth
        self.tpr_smooth += (t_pr - self.tpr_smooth) / 60.0
        # heat balance: tank, boilers, supply temperature
        p_net = C_W * q_pump * (ts_set - t_pr) if q_pump > 1e-6 else 0.0
        rate = self.cur["tank_rate"]
        discharge = 0.0
        charge_req = 0.0
        if rate < 0.0:
            discharge = min(-rate, self.tank_e / DT_H, max(0.0, p_net))
        else:
            charge_req = min(rate, max(0.0, (p["E_tank"] - self.tank_e) / DT_H))
        caps = {b: p["cap"][BOILERS.index(b)] for b in self.boilers}
        cap_on = sum(caps.values())
        need = max(0.0, p_net - discharge)
        boiler_out = min(need + charge_req, cap_on)
        charge = max(0.0, min(charge_req, boiler_out - need))
        to_network = boiler_out - charge
        supplied = to_network + discharge
        if q_pump > 1e-6 and supplied < p_net - 1e-9:
            ts_act = t_pr + supplied / (C_W * q_pump)
        else:
            ts_act = ts_set
        self.ts_hist.append(ts_act)
        # dispatch in staging order
        out_b = [0.0, 0.0, 0.0]
        rest = boiler_out
        for b in self.boilers:
            j = BOILERS.index(b)
            take = min(rest, caps[b])
            out_b[j] = take
            rest -= take
        fuel = [0.0, 0.0, 0.0]
        eta_b = [0.0, 0.0, 0.0]
        for j, b in enumerate(BOILERS):
            eta = self._eta(j, b, hour, out_b[j])
            eta_b[j] = eta
            fuel[j] = out_b[j] / eta if out_b[j] > 0.0 else 0.0
        h_idx = int(hour)
        price = tariff(h_idx)
        step_cost = sum(fuel) * price * DT_H
        charge_share = charge / boiler_out if boiler_out > 1e-9 else 0.0
        # tank energy and its average cost
        avg_cost = self.tank_cost / self.tank_e if self.tank_e > 1e-9 else 0.0
        self.tank_cost += step_cost * charge_share - discharge * DT_H * avg_cost
        self.tank_e += (charge - discharge) * DT_H
        loss = self.tank_e * TANK_LOSS_PER_H * DT_H
        self.tank_cost -= loss * (
            self.tank_cost / self.tank_e if self.tank_e > 1e-9 else 0.0
        )
        self.tank_e -= loss
        if self.tank_e < 0.0:
            self.tank_e = 0.0
            self.tank_cost = 0.0
        # graded window
        if i >= WINDOW_START:
            self.win_heat += sum(heat) * DT_H
            for k in range(6):
                self.win_heat_k[k] += heat[k] * DT_H
            self.win_demand += sum(loads) * DT_H
            self.win_cost += (
                step_cost * (1.0 - charge_share) + discharge * DT_H * avg_cost
            )
            for k in range(6):
                if tr_act[k] < FLOOR_C:
                    self.win_below[k] += 1
                if tr_act[k] < self.win_min_return[k]:
                    self.win_min_return[k] = tr_act[k]
        if self.observer is not None:
            self.observer.observe(
                i,
                {
                    "ts": ts_act,
                    "tpr": t_pr,
                    "qp": q_pump,
                    "qn": q_near,
                    "qf": q_far,
                    "byp": bypass,
                    "pin": p_in,
                    "lev": level,
                    "tank": charge - discharge,
                    "spd": speed,
                    "amb": t_amb,
                    "out_b": out_b,
                    "fuel": fuel,
                    "tr": tr_act,
                    "q": q,
                    "heat": heat,
                    "u_far": max(0.0, min(1.0, self.u_valve)),
                },
            )
        # event log
        if not self.b2_fault_logged and hour >= p["h_b2fault"]:
            self.b2_fault_logged = True
            self.events.append(
                {
                    "step": i,
                    "source": "RTU-BLR",
                    "event": "fault_code",
                    "subject": "B2",
                    "code": "E-31",
                }
            )
        if not self.unit_logged and hour >= p["h_unit"]:
            self.unit_logged = True
            self.events.append(
                {
                    "step": i,
                    "source": "RTU-" + SUBSTATIONS[p["unit_sub"]],
                    "event": "firmware_update",
                    "subject": "RTU-" + SUBSTATIONS[p["unit_sub"]],
                    "version": "4.2.0",
                }
            )
        self.step_index += 1

    def _eta(self, j: int, b: str, hour: float, out: float) -> float:
        p = self.p
        base = p["eta0"][j]
        if j == 1 and hour >= p["h_b2fault"]:
            base = p["b2_eta_after"]
        lf = out / p["cap"][j] if p["cap"][j] > 0 else 0.0
        eta = base - 0.03 * (1.0 - lf) * (1.0 - lf)
        dew = DEW_POINT_A - DEW_POINT_B * (LAMBDA[b] - 1.0)
        below = dew - self.tpr_smooth
        if below > 0.0:
            eta += p["cond_gain"][j] * min(below, 10.0)
        return eta

    # ------------------------------------------------------------------ grading
    def metrics(self) -> dict:
        """O1-O4 from a run advanced to step N_STEPS."""
        if self.step_index < N_STEPS:
            raise RuntimeError("metrics need the full 72 hours")
        heat = self.win_heat
        unit_cost = self.win_cost / heat if heat > 1e-9 else float("inf")
        below_s = [n * STEP_S for n in self.win_below]
        return {
            "delivered_mwh": heat,
            "delivered_by_customer": list(self.win_heat_k),
            "demand_mwh": self.win_demand,
            "unit_cost": unit_cost,
            "below_floor_s": below_s,
            "min_return": self.win_min_return,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "O1": 1 if heat >= CONTRACTED_MWH else 0,
            "O2": 1 if max(below_s) <= 600 else 0,
            "O3": 1 if unit_cost <= COST_CAP else 0,
            "O4": 1 if self.accepted <= 40 and self.rejected == 0 else 0,
        }


def validate(change: dict) -> dict:
    if not isinstance(change, dict) or not change:
        raise ControlError(
            "a control request sets at least one of supply_temp, pump_speed, boilers, tank_rate"
        )
    clean: dict = {}
    for key, value in change.items():
        if key in LIMITS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ControlError(f"{key} must be a number")
            lo, hi = LIMITS[key]
            if not (lo <= float(value) <= hi):
                raise ControlError(f"{key} must be between {lo:g} and {hi:g}")
            clean[key] = round(float(value), 3)
        elif key == "boilers":
            if (
                not isinstance(value, list)
                or not value
                or len(set(value)) != len(value)
                or any(b not in BOILERS for b in value)
            ):
                raise ControlError(
                    "boilers must be a non-empty ordered list of distinct ids from B1, B2, B3"
                )
            clean[key] = list(value)
        else:
            raise ControlError(f"unknown control {key!r}")
    return clean
