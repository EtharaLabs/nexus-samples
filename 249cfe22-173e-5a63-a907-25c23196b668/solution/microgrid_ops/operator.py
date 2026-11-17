"""The expert reference operating policy and its naive variants.

The policy sees only the EMS API and the shipped documents (``manual``). Each naive variant replaces
exactly one component of the expert procedure; ``VARIANTS`` names them.
"""

from __future__ import annotations

import statistics

from . import design as D
from . import manual as M

VARIANTS = {
    "reference": "expert procedure",
    "R1-averaged-telemetry": "reads only 15-minute battery power, so sees no inverter derate",
    "R2-grid-tied-extrapolation": "runs no low-load test; assumes the gensets are stable at 20 percent load",
    "R3-dr-as-trip": "reports the Annex C demand-response load group as an equipment fault",
    "R4-two-light-gensets": "fits a flat fuel curve; shares the load over both gensets",
    "R5-pv-attribution": "attributes the genset fuel rise to the PV ramp; keeps the faulted genset on duty",
    "R6-trusts-streams": "never checks sequence numbers or uptime counters",
    "R7-logged-points": "reads the minimum stable load off the logged excursions",
    "R8-shed-everything": "sheds every non-critical group for the outage",
    "R9-ignores-tariff": "charges the battery from imports in the first hours it can, whatever the tariff",
    "one-at-a-time": "tunes one control at a time against a separable model",
    "no-monitoring-after-20": "stops reading telemetry and events after hour 20",
    "no-battery-precharge": "never charges the battery from imports",
    "RV-CRIT-retroactive": "applies the critical-list revision from its issued hour",
    "blanket-safe": "conservative fixed settings for every seed, no experiments",
    "best-fixed-plan": "the best single plan across the documented ranges, no discovery",
    "opening-spec-only": "the reference with the message channel never read",
}
FIXED = ("blanket-safe", "best-fixed-plan")
TAG_RTU = {"F-SYS": "RTU-BUS", "PT-TIE": "RTU-BUS", "PT-PV": "RTU-BUS", "PT-BAT": "RTU-BUS",
           "SOC-BAT": "RTU-BUS", "PG-G1": "RTU-GEN", "PG-G2": "RTU-GEN", "FQ-G1": "RTU-GEN",
           "FQ-G2": "RTU-GEN", "F-GEN": "RTU-FREQ"}
for _g in M.GROUPS:
    TAG_RTU["PM-" + _g] = "RTU-" + _g


class Telemetry:
    def __init__(self, packets: list[dict]):
        self.by_rtu: dict[str, list[dict]] = {}
        for pk in packets:
            self.by_rtu.setdefault(pk["rtu"], []).append(pk)

    def series(self, tag: str, lo: float = 0.0, hi: float = 1e9) -> list[tuple[float, float]]:
        out = []
        for pk in self.by_rtu.get(TAG_RTU[tag], []):
            t = pk["interval_start_h"]
            v = pk["values"].get(tag)
            if v is not None and lo <= t < hi:
                out.append((t, v))
        return out

    def last(self, tag: str) -> float:
        return self.series(tag)[-1][1]


class Operator:
    def __init__(self, client, variant: str = "reference"):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.c = client
        self.v = variant
        self.log: list[str] = []
        self.est: dict = {"pmin": None, "knee": None, "cap": 12.0}
        self.healthy = "G1"
        self.faulty: str | None = None
        self.fault_hour: float | None = None
        self.bias: dict = {}
        self.msgs: dict[str, dict] = {}
        self.plan: dict = {}
        self.found: dict = {}

    # ------------------------------------------------------------------ helpers
    def note(self, text: str) -> None:
        self.log.append(text)

    def hour(self) -> float:
        return self.c.status()["plant_hour"]

    def change(self, at: float, change: dict) -> None:
        self.c.wait_until(at)
        st = self.c.status()
        if st["ramp_active"]:
            self.c.wait_until(st["plant_hour"] + st["ramp_remaining_s"] / 3600.0 + 0.003)
        res = self.c.control(change)
        if not res.get("accepted"):
            raise RuntimeError(f"control rejected at {res.get('plant_hour')}: {res}")
        self.note(f"h{res['plant_hour']:.2f} change {change}")

    def telemetry(self) -> Telemetry:
        return Telemetry(self.c.telemetry(0.0)["packets"])

    def read_messages(self) -> None:
        if self.v == "opening-spec-only":
            return
        for m in self.c.messages()["messages"]:
            self.msgs[m["id"]] = m

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        v = self.v
        if v in FIXED:
            return self._fixed_plan()
        self._initial_charge()
        self._low_load_test()
        self._derate_test()
        self._monitor_day()
        self._checks()
        self._precharge()
        self._window()
        self.c.wait_until(72.0)
        return {"variant": v, "incidents": self.report(), "plan": self.plan, "log": self.log,
                "self_check": self.self_check()}

    # ------------------------------------------------------------------ experiments
    def _initial_charge(self) -> None:
        self.change(0.1, {"g1_mw": 0.0, "g2_mw": 0.0, "bat_mw": -2.5})
        self.c.wait_until(3.8)
        tel = self.telemetry()
        soc = tel.series("SOC-BAT", 0.0, 3.8)
        pb = dict(tel.series("PT-BAT", 0.0, 3.8))
        # battery capacity from the energy it took in while charging at a steady rate
        pairs = [(t, s) for t, s in soc if t >= 0.4 and pb.get(t, 0.0) < -2.0]
        if len(pairs) >= 4 and not self.v.startswith("opening"):
            (t0, s0), (t1, s1) = pairs[0], pairs[-1]
            e_in = -sum(pb[t] for t, _ in pairs[:-1]) * 0.25 * M.BAT_EFF
            if s1 - s0 > 5.0:
                self.est["cap"] = e_in / ((s1 - s0) / 100.0)
        self.change(3.9, {"bat_mw": 0.0})

    def _low_load_test(self) -> None:
        v = self.v
        if v == "R2-grid-tied-extrapolation":
            self.est["pmin"] = 0.2 * M.G_RATED
            self.note(f"no low-load test; stable load taken as {self.est['pmin']:.2f} MW")
            return
        levels = [2.00, 1.75, 1.50, 1.25, 1.00, 0.75, 0.50, 0.25]
        t = 4.2
        rows = []
        for sp in levels:
            self.change(t, {"g1_mw": sp})
            start = self.hour() + 0.36
            self.c.wait_until(start + 0.5 + 0.004)
            pts = self.c.raw(["F-GEN"], start)["samples"]["F-GEN"]
            rows.append((sp, pts))
            t = self.hour() + 0.02
        self.change(t, {"g1_mw": 0.0})
        self.est["pmin"], self.found["pmin_rows"] = D.pmin_from_rows(rows, naive=(v == "R7-logged-points"))
        self.note(f"minimum stable load {self.est['pmin']:.4f} MW")
        self.t_after_low = self.hour()

    def _derate_test(self) -> None:
        levels = [1.40, 1.46, 1.52, 1.58, 1.64]
        if self.v == "R1-averaged-telemetry":
            t = max(self.hour(), 12.0) + 0.1
            self.change(t, {"bat_mw": 2.0})
            self.c.wait_until(t + 1.6)
            tel = self.telemetry()
            self.est["knee"] = None
            self.found["pt_bat_avg"] = [v_ for _, v_ in tel.series("PT-BAT", t + 0.5, t + 1.6)]
            self.change(self.hour() + 0.02, {"bat_mw": 0.0})
            self.note("battery power reads steady in 15-minute averages; no derate seen")
            return
        t = max(self.hour(), 11.0) + 0.1
        rows = []
        for b in levels:
            self.change(t, {"bat_mw": b})
            start = self.hour() + 0.36
            self.c.wait_until(start + 0.5 + 0.004)
            samples = self.c.raw(["PT-BAT"], start)["samples"]["PT-BAT"]
            rows.append((b, [x[1] for x in samples]))
            t = self.hour() + 0.02
        self.change(t, {"bat_mw": 0.0})
        self.est["knee"] = D.knee_from_rows(rows)
        self.note(f"inverter derate knee {self.est['knee']:.4f} MW")

    def _monitor_day(self) -> None:
        self._fault_check()
        if self.v == "R9-ignores-tariff":
            # charges as soon as the evening peak tariff starts, whatever Annex B says
            self.c.wait_until(40.0)
            soc = self.telemetry().last("SOC-BAT") / 100.0
            length = max(0.0, (D.SOC_TARGET - soc) * self.est["cap"]) / (M.BAT_EFF * D.CHARGE_MW) + D.RAMP_LOSS_H
            self.change(40.1, {"bat_mw": -D.CHARGE_MW})
            self.change(40.1 + length, {"bat_mw": 0.0})
        self.c.wait_until(46.0 if self.v != "no-monitoring-after-20" else 20.0)

    # ------------------------------------------------------------------ evidence
    def _fault_check(self) -> None:
        """Run both gensets at one load and compare each unit's fuel-to-power balance with the datasheet."""
        t = self.hour()
        ev = [e for e in self.c.events(0.0)["events"] if e.get("event") == "fault_code"]
        while not ev:
            t = max(t, self.hour()) + 0.5
            self.c.wait_until(t)
            ev = [e for e in self.c.events(0.0)["events"] if e.get("event") == "fault_code"]
            if t > 20.0:
                return
        self.fault_hour = ev[0]["hour"]
        self.faulty = ev[0]["subject"]
        if self.v == "R5-pv-attribution":
            self.healthy = self.faulty  # the fuel rise is put down to the PV ramp; the unit stays on duty
            self.note(f"fault code on {self.faulty} put down to the PV ramp")
            return
        t0 = max(self.hour(), self.fault_hour) + 0.1
        self.change(t0, {"g1_mw": 1.6, "g2_mw": 1.6})
        self.c.wait_until(t0 + 1.35)
        tel = self.telemetry()
        eff = {}
        for g in ("G1", "G2"):
            pg = dict(tel.series("PG-" + g, t0 + 0.5, t0 + 1.4))
            fq = dict(tel.series("FQ-" + g, t0 + 0.5, t0 + 1.4))
            vals = [pg[k] / fq[k] for k in pg if k in fq and fq[k] > 0.5]
            eff[g] = statistics.fmean(vals) / M.eta(1.6 / M.G_RATED) if vals else 1.0
        self.change(self.hour() + 0.02, {"g1_mw": 0.0, "g2_mw": 0.0})
        bad = min(eff, key=eff.get)
        self.faulty = bad if eff[bad] < 0.92 else None
        self.healthy = "G2" if self.faulty == "G1" else "G1"
        self.found["gen_eff"] = eff
        self.note(f"fuel-to-power balance against the datasheet: {eff}")

    def _checks(self) -> None:
        """D2 evidence from telemetry and the event log up to the hour the checks run."""
        v = self.v
        horizon = 20.0 if v == "no-monitoring-after-20" else self.hour()
        tel = Telemetry([pk for pk in self.c.telemetry(0.0)["packets"] if pk["interval_end_h"] <= horizon])
        ev = [e for e in self.c.events(0.0)["events"] if e["hour"] <= horizon]
        out: list[dict] = []
        replay_start = None
        if v != "R6-trusts-streams":
            for rtu, pks in tel.by_rtu.items():
                for a, b in zip(pks, pks[1:]):
                    if b["seq"] <= a["seq"]:
                        out.append({"kind": "sensor", "subject": rtu, "onset_hour": b["interval_start_h"], "value": None})
                        replay_start = (rtu, b["interval_start_h"])
                        break
        for e in ev:
            if e.get("event") == "firmware_update" and str(e.get("subject", "")).startswith("RTU-"):
                tag = "PM-" + e["subject"][4:]
                before = [x for _, x in tel.series(tag, e["hour"] - 3.0, e["hour"])]
                after = [x for _, x in tel.series(tag, e["hour"] + 0.25, e["hour"] + 3.0)]
                if before and after and statistics.median(after) > 100.0 * statistics.median(before):
                    out.append({"kind": "sensor", "subject": tag, "onset_hour": e["hour"], "value": None})
                    self.found["unit_tag"] = tag
        if v != "no-monitoring-after-20" or horizon >= 20.0:
            bias = D.find_bias(tel)
            if bias:
                out.append({"kind": "sensor", "subject": bias[0], "onset_hour": 0.0, "value": None})
                self.bias = {bias[0]: bias[1]}
            skip = {self.found.get("unit_tag"), bias[0] if bias else None}
            if replay_start:
                skip.add("PM-" + replay_start[0][4:])
            drift = D.find_drift(tel, skip=skip)
            if drift:
                out.append({"kind": "sensor", "subject": drift[0], "onset_hour": round(drift[1], 3), "value": None})
        if self.faulty and v != "R5-pv-attribution":
            out.append({"kind": "equipment", "subject": self.faulty, "onset_hour": self.fault_hour, "value": None})
        self.d2 = out

    # ------------------------------------------------------------------ charging
    def _dr_hours(self, tel_events: list[dict]) -> list[tuple[float, float]]:
        """Annex C demand-response hours as known: the notice in the event log, and the revision."""
        win = []
        for e in tel_events:
            if e.get("event") == "dr_notice":
                win.append([e["start_hour"], e["end_hour"]])
        rv = self.msgs.get("RV-DR")
        if rv and win:
            win[-1][1] = max(win[-1][1], rv["terms"]["event_end_hour"])
        return [(a, b) for a, b in win] + [(float(M.DR_EVENT0[0]), float(M.DR_EVENT0[1]))]

    def _precharge(self) -> None:
        v = self.v
        self.c.wait_until(46.2)
        self.read_messages()
        rv = self.msgs.get("RV-OUT")
        self.t_open = rv["terms"]["tie_open_hour"] if rv else float(M.TIE_OPEN0)
        events = self.c.events(0.0)["events"]
        tel = self.telemetry()
        soc = tel.last("SOC-BAT") / 100.0
        need = max(0.0, (D.SOC_TARGET - soc) * self.est["cap"])
        self.note(f"hour {self.hour():.2f}: tie opens {self.t_open}, battery {soc:.3f}, need {need:.2f} MWh")
        blocks = []
        if v not in ("no-battery-precharge", "R9-ignores-tariff") and need > 0.3:
            blocks = D.charge_blocks(self.hour() + 0.05, self.t_open, need, self._dr_hours(events)) or []
        for a, b in blocks:
            self.change(a, {"bat_mw": -D.CHARGE_MW})
            self.change(b, {"bat_mw": 0.0})
        self.plan["charge_blocks"] = [[round(a, 2), round(b, 2)] for a, b in blocks]
        self.change(max(self.hour(), self.t_open - 0.5), {"g1_mw": 1.5, "g2_mw": 1.5})
        self.c.wait_until(self.t_open + 0.1)

    # ------------------------------------------------------------------ the window
    def _profile(self, tel: Telemetry) -> dict[str, list[float]]:
        """Hourly demand of each group for plant hours 66 to 72, read from day 1 at the same clock
        hours (the meters repeat daily); a biased meter is corrected by its balance coefficient. The
        last hour copies the one before it: a replaying RTU's packets are unreliable near hour 24."""
        out = {}
        for g in M.GROUPS:
            ser = D._pm(tel, g, 18.0, 23.0)
            hours = []
            for h in range(18, 23):
                vals = [x for t, x in ser.items() if h <= t < h + 1]
                hours.append(statistics.fmean(vals) if vals else 0.0)
            hours.append(hours[-1])
            k = self.bias.get("PM-" + g)
            if k:
                hours = [x * (1.0 - k) for x in hours]
            out[g] = hours
        return out

    def _window(self) -> None:
        v = self.v
        self.c.wait_until(65.0)
        self.read_messages()
        crit0 = set(M.CRIT0)
        rv = self.msgs.get("RV-CRIT")
        new = set(rv["terms"]["critical_from_effective"]) if rv else crit0
        crit_union = crit0 | new
        shed_ok = [g for g in M.GROUPS if g not in crit_union]
        force_shed: list[str] = []
        if v == "RV-CRIT-retroactive" and rv:
            shed_ok = [g for g in M.GROUPS if g not in new]
            force_shed = sorted(crit0 - new, key=M.GROUPS.index)
        tel = self.telemetry()
        prof = self._profile(tel)
        soc = tel.last("SOC-BAT") / 100.0
        e_dc = max(0.0, (soc - 0.06) * self.est["cap"])
        if v == "no-battery-precharge":
            e_dc = (0.98 - 0.06) * self.est["cap"]  # plans on the energy a precharged battery holds
        pmin = self.est["pmin"]
        knee = self.est["knee"]
        kw = dict(bat_cost=90.0, flat=(v == "R4-two-light-gensets"), margin_p=0.0 if v in ("R2-grid-tied-extrapolation", "R4-two-light-gensets") else 0.12,
                  low_gen=(v == "R2-grid-tied-extrapolation"),
                  max_bat=(v == "R1-averaged-telemetry"),
                  n_gens=2 if v == "R4-two-light-gensets" else (1 if v == "R2-grid-tied-extrapolation" else None))
        if v == "R8-shed-everything":
            # shedding is taken to be free: every non-critical group goes, and the genset is run at
            # the lowest load the datasheet tabulates, the battery carrying the rest
            load = [sum(x[k] for g, x in prof.items() if g not in shed_ok) for k in range(6)]
            cap_b = min(D.CHARGE_MW, (knee or D.CHARGE_MW) - 0.06, e_dc * M.BAT_EFF / 6.0)
            b = max(0.0, min(cap_b, min(load) - 0.6))
            plan = {"shed": list(shed_ok), "bat": round(b, 3), "sp_total": round(max(0.6, max(load) - b - 0.45), 3), "n": 1}
        elif v == "one-at-a-time":
            plan = self._one_at_a_time(prof, shed_ok, e_dc)
        elif force_shed:
            prof_f = {g: ([0.0] * 6 if g in force_shed else x) for g, x in prof.items()}
            rest = [g for g in shed_ok if g not in force_shed]
            plan = D.plan_window(prof_f, rest, e_dc, knee, pmin, **kw)
            plan = dict(plan or {}, shed=sorted(set(plan["shed"]) | set(force_shed), key=M.GROUPS.index)) if plan else None
        else:
            plan = D.plan_window(prof, shed_ok, e_dc, knee, pmin, **kw)
        self.plan.update({"window": plan, "soc_at_65": round(soc, 4), "e_dc": round(e_dc, 3)})
        if plan is None:
            plan = {"shed": [], "bat": 0.0, "sp_total": 2.0}
            self.plan["fallback"] = True
        sp = plan["sp_total"]
        change = {"bat_mw": plan["bat"], "shed": plan["shed"]}
        if plan.get("n") == 2:
            change.update({"g1_mw": round(sp / 2, 3), "g2_mw": round(sp / 2, 3)})
        elif self.healthy == "G1":
            change.update({"g1_mw": round(sp, 3), "g2_mw": 0.0})
        else:
            change.update({"g1_mw": 0.0, "g2_mw": round(sp, 3)})
        self.change(65.6, change)

    def _one_at_a_time(self, prof, shed_ok, e_dc) -> dict:
        """Each control tuned alone against a separable model: the set point for best efficiency
        with the battery idle, then the battery for the energy it holds, then no shedding."""
        load = [sum(v[k] for v in prof.values()) for k in range(6)]
        return {"shed": [], "bat": 0.0, "sp_total": round(0.8 * M.G_RATED, 3), "unit_cost": None}

    # ------------------------------------------------------------------ fixed plans
    def _fixed_plan(self) -> dict:
        v = self.v
        spec = FIXED_PLANS[v]
        self._initial_charge()
        self.c.wait_until(spec.get("charge_at", 54.0))
        if spec.get("charge_hours"):
            self.change(spec["charge_at"], {"bat_mw": -D.CHARGE_MW})
            self.change(spec["charge_at"] + spec["charge_hours"], {"bat_mw": 0.0})
        self.change(spec["open_gens_at"], {"g1_mw": spec["pre_gen"], "g2_mw": spec["pre_gen"]})
        self.change(65.6, spec["window"])
        self.c.wait_until(72.0)
        incidents = [{"kind": "contract", "subject": "DOCK", "onset_hour": None, "value": None}]
        return {"variant": v, "incidents": incidents, "plan": spec, "log": self.log, "self_check": {"ok": True}}

    # ------------------------------------------------------------------ report
    def report(self) -> list[dict]:
        v = self.v
        out = list(self.d2)
        if v == "R3-dr-as-trip":
            out.append({"kind": "equipment", "subject": "DOCK", "onset_hour": 11.0, "value": None})
        else:
            out.append({"kind": "contract", "subject": "DOCK", "onset_hour": None, "value": None})
        if self.est["knee"] is not None:
            out.append({"kind": "operating_limit", "subject": "PT-BAT", "onset_hour": None,
                        "value": round(self.est["knee"], 4)})
        if self.est["pmin"] is not None:
            out.append({"kind": "operating_limit", "subject": "PG-GEN", "onset_hour": None,
                        "value": round(self.est["pmin"], 4)})
        return out

    def self_check(self) -> dict:
        """Each policy's own evidence: its plan was feasible under what it believed."""
        plan = self.plan.get("window")
        return {"plan_found": plan is not None, "believed_pmin": self.est["pmin"],
                "believed_knee": self.est["knee"], "reported": len(self.report())}


FIXED_PLANS = {
    "blanket-safe": {"charge_at": 0.0, "charge_hours": 0.0, "open_gens_at": 50.0, "pre_gen": 1.5,
                     "window": {"g1_mw": 1.5, "g2_mw": 1.5, "bat_mw": 0.0, "shed": []}},
    # the best plan of a search over the documented ranges (feasibility/fixedsearch3.py): one genset
    # near its best-efficiency load, the battery just under the lowest derate power, DOCK shed
    "best-fixed-plan": {"charge_at": 54.0, "charge_hours": 0.0, "open_gens_at": 53.0, "pre_gen": 1.5,
                        "window": {"g1_mw": 2.4, "g2_mw": 0.0, "bat_mw": 1.35, "shed": ["DOCK"]}},
}
