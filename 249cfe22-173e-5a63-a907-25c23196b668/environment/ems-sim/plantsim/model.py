"""The island microgrid: loads, PV, battery with its inverter, two gensets, the utility tie.

One simulation step is 10 s; frequency and the battery inverter output carry 10 samples per step
(1 s). All transcendentals come from plantops.detmath so the run is bit-identical across
architectures.
"""

from __future__ import annotations

from plantops import detmath as dm

from . import terms as T
from .params import BAND, GROUPS, N_STEPS, SPH, SUB, WINDOW_START, draw

TWO_PI = 6.283185307179586
G_RATED = 3.0
ETA_MAX, ETA_X0, ETA_K = 0.40, 0.78, 0.35  # genset efficiency curve (datasheet)
ETA_BAT = 0.96  # one-way inverter and cell efficiency
BAT_LOSS_PER_H = 0.0004
BAT_MIN_SOC, BAT_MAX_SOC = 0.05, 0.98
RESIDUAL_STIFF = 0.25  # blackout stiffness with no genset online
UFLS_DF = 0.45  # Hz: the under-frequency relays shed load before the frequency falls 0.45 Hz
PV_SUNRISE, PV_SUNSET = 6.5, 18.0
HUNT_BUS_ATTEN = 0.3  # share of a hunt that shows on the genset bus while the tie is closed


def eta(x: float) -> float:
    return ETA_MAX - ETA_K * (x - ETA_X0) ** 2


def fuel_mw(out: float, gov_loss: float = 0.0) -> float:
    """Fuel input (MW, net calorific value) of a genset delivering ``out`` MW."""
    if out <= 1e-9:
        return 0.0
    return out / (eta(out / G_RATED) * (1.0 - gov_loss))


def pv_shape(clock_h: float) -> float:
    if clock_h <= PV_SUNRISE or clock_h >= PV_SUNSET:
        return 0.0
    return dm.sin(3.141592653589793 * (clock_h - PV_SUNRISE) / (PV_SUNSET - PV_SUNRISE)) ** 2


def pv_mw(p: dict, hour: float, shift: float = 0.0) -> float:
    day = int(hour // 24)
    cloud = p["pv_cloud"][day % 4]
    dip = 0.45 if abs(hour - p["h_dip"]) < 1.0 and shift == 0.0 else 1.0
    return p["pv_peak"] * cloud * dip * pv_shape((hour - shift) % 24.0)


def load_mw(p: dict, group: str, hour: float, shift: float = 0.0) -> float:
    return T.nominal_mw(group, hour - shift) * p["load_scale"][group]


class Plant:
    """Physics and grading accumulators. ``observer`` receives (step, true values) each step."""

    def __init__(self, seed: int, gate, events: list, observer=None):
        self.p = p = draw(seed)
        self.gate = gate
        self.events = events
        self.observer = observer
        self.i = 0
        self.E = p["soc0"] * p["bat_cap"]
        self.Cs = T.BAT_COST0
        self.fired: set = set()
        self.m = {
            "cost_fuel": 0.0, "cost_import": 0.0, "cost_bat": 0.0, "served": 0.0,
            "out_s": 0, "seg": {}, "min_gen": 9.0, "import_pen_mwh": 0.0, "unserved_mwh": 0.0,
            "bat_min_soc": 1.0, "hunt_s": 0, "bat_end_mwh": 0.0,
        }
        self.seg_bounds = T.segments(p)
        for k, (a, b, groups) in enumerate(self.seg_bounds):
            self.m["seg"][k] = {"a": a, "b": b, "groups": list(groups), "mwh": 0.0,
                                "contract": round(T.contracted_mwh(p, a, b, groups), 4)}

    # -------------------------------------------------------------- events
    def _fire(self, i: int, hour: float) -> None:
        p, ev = self.p, self.events
        for msg in T.messages(p):
            key = ("msg", msg["id"])
            if key not in self.fired and hour >= msg["issued_hour"]:
                self.fired.add(key)
                ev.append({"step": i, "source": "MSG", "event": "message_received", "id": msg["id"]})
        gen = p["gens"][p["fault_gen"]]
        for key, when, row in (
            ("gov", p["h_gov"], {"source": "EMS", "event": "fault_code", "subject": gen, "code": "E-31"}),
            ("fw", p["h_unit"], {"source": "EMS", "event": "firmware_update",
                                 "subject": "RTU-" + p["unit_tag"][3:]}),
            ("drn", p["dr_start"] - 20.0,
             {"source": "EMS", "event": "dr_notice", "subject": p["dr_group"],
              "start_hour": p["dr_start"], "end_hour": p["dr_start"] + p["dr_len"]}),
            ("tie", p["h_out1"],
             {"source": "EMS", "event": "tie_opened", "subject": "TIE"}),
        ):
            if key not in self.fired and hour >= when:
                self.fired.add(key)
                ev.append(dict(row, step=i))

    # -------------------------------------------------------------- one step
    def step(self) -> None:
        i, p, g = self.i, self.p, self.gate
        hour = i / SPH
        dt = 1.0 / SPH
        g.tick(i)
        self._fire(i, hour)
        sp = [g.value("g1_mw"), g.value("g2_mw")]
        cmd = g.value("bat_mw")
        curt, shed = g.value("pv_curtail"), g.value("shed")
        cmd = max(-p["bat_inv"], min(p["bat_inv"], cmd))
        if cmd > 0 and self.E <= BAT_MIN_SOC * p["bat_cap"]:
            cmd = 0.0
        if cmd < 0 and self.E >= BAT_MAX_SOC * p["bat_cap"]:
            cmd = 0.0
        if cmd < 0 and hour >= p["h_out1"] and sp[0] <= 0.01 and sp[1] <= 0.01:
            # islanded with both gensets out of service, PV serves the load first and nothing
            # is left to charge the battery
            cmd = 0.0
        sag = 0.0
        if cmd > p["p_derate"]:
            sag = min(0.5, p["derate_gain"] * (cmd - p["p_derate"]))
        bat_k = []
        for k in range(SUB):
            t = i * 10 + k
            wave = 1.0 if (t % p["derate_period_s"]) < 0.2 * p["derate_period_s"] else 0.0
            bat_k.append(cmd * (1.0 - sag * wave))
        bat = sum(bat_k) / SUB
        dem = {}
        dropped = T.dr_active(p, hour)
        for grp in GROUPS:
            d = 0.0 if grp == dropped else load_mw(p, grp, hour)
            dem[grp] = 0.0 if grp in shed else d
        load = sum(dem.values())
        pv = pv_mw(p, hour) * (1.0 - curt)
        imb = load - pv - bat - sp[0] - sp[1]
        closed = hour < p["h_out1"]
        k_g = G_RATED / (p["droop"] * 50.0)
        out = [0.0, 0.0]
        residual = 0.0
        if closed:
            tie, out, df = imb, list(sp), 0.0
        else:
            tie = 0.0
            online = [s_ > 0.01 for s_ in sp]
            kk = k_g * sum(online)
            if kk > 0:
                # under-frequency relays shed load rather than let the frequency fall below the floor
                room = sum(min(G_RATED - sp[j], k_g * UFLS_DF) for j in (0, 1) if online[j])
                shed_mw = max(0.0, imb - room)
                imb_eff = imb - shed_mw
                for j in (0, 1):
                    if online[j]:
                        out[j] = max(0.0, min(G_RATED, sp[j] + imb_eff * k_g / kk))
                delta = (out[0] - sp[0]) + (out[1] - sp[1])
                residual = max(0.0, imb - delta)
                df = -delta / kk + max(0.0, delta - imb) / RESIDUAL_STIFF
            else:
                residual = imb
                df = -residual / RESIDUAL_STIFF
            df = max(-15.0, min(15.0, df))
            df -= 0.02 * (pv - getattr(self, "pv_prev", pv)) * SPH * bat
        self.pv_prev = pv
        unserved = min(max(residual, 0.0), load) if not closed else 0.0
        frac = 1.0 - (unserved / load if load > 1e-9 else 0.0)
        hunt = []
        for j in (0, 1):
            if out[j] > 0.01 and sp[j] > 0.01 and out[j] < p["pmin"]:
                hunt.append((j, p["hunt_k"] * (p["pmin"] - out[j])))
        f_sys, f_bus = [], []
        for k in range(SUB):
            t = i * 10 + k
            h_sum = sum(a * dm.sin(TWO_PI * t / p["hunt_period_s"] + 0.7 * (j + 1)) for j, a in hunt)
            f_sys.append(50.0 + df + (h_sum if not closed else 0.0))
            f_bus.append(50.0 + df + (h_sum if not closed else HUNT_BUS_ATTEN * h_sum))
        loss = [0.0, 0.0]
        loss[p["fault_gen"]] = p["gov_eta_loss"] if hour >= p["h_gov"] else 0.0
        fuel = [fuel_mw(out[j], loss[j]) for j in (0, 1)]
        fuel_cost = (fuel[0] + fuel[1]) * T.FUEL_PRICE
        imp = max(tie, 0.0)
        price = T.DR_PENALTY if T.dr_active(p, hour) else T.tariff(hour)
        imp_cost = imp * price
        if bat > 0:
            e_dc = bat / ETA_BAT * dt
            self.E -= e_dc
            cost_bat = e_dc * self.Cs
        else:
            cost_bat = 0.0
            if bat < 0:
                supply = out[0] + out[1] + imp
                rate = (fuel_cost + imp_cost) / supply if supply > 1e-9 else 0.0
                e_in = -bat * ETA_BAT * dt
                self.Cs = (self.Cs * self.E + (-bat) * rate * dt) / (self.E + e_in)
                self.E += e_in
        self.E *= 1.0 - BAT_LOSS_PER_H * dt
        if i >= WINDOW_START:
            m = self.m
            m["cost_fuel"] += fuel_cost * dt
            m["cost_import"] += imp_cost * dt
            m["cost_bat"] += cost_bat
            served = {grp: dem[grp] * frac for grp in GROUPS}
            m["served"] += sum(served.values()) * dt
            m["unserved_mwh"] += unserved * dt
            m["out_s"] += sum(1 for f in f_sys if f < BAND[0] or f > BAND[1])
            for j in (0, 1):
                if sp[j] > 0.01:
                    m["min_gen"] = min(m["min_gen"], out[j])
            m["hunt_s"] += SUB if hunt else 0
            m["bat_min_soc"] = min(m["bat_min_soc"], self.E / p["bat_cap"])
            for sg in m["seg"].values():
                if sg["a"] <= hour < sg["b"]:
                    sg["mwh"] += sum(served[grp] for grp in sg["groups"]) * dt
        if self.observer is not None:
            self.observer(i, {
                "load": dem, "pv": pv, "bat": bat_k, "tie": tie, "out": out, "fuel": fuel,
                "f_sys": f_sys, "f_bus": f_bus, "soc": self.E / p["bat_cap"], "hour": hour,
                "drop": dropped,
            })
        self.i += 1
