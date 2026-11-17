"""The expert reference operating policy and its naive variants.

The policy sees only the SCADA API and the shipped documents (``manual``). Each naive variant
replaces exactly one component of the expert procedure; ``VARIANTS`` names them.
"""

from __future__ import annotations

import statistics

from . import designcalc as D
from . import manual as M

VARIANTS = {
    "reference": "expert procedure",
    "R1-averaged-telemetry": "never reads raw samples; sizes pump flow at 1.035 x need",
    "R2-mild-extrapolation": "no high-load probe; assumes the far branch responds linearly",
    "R3-setback-as-fault": "reports the Annex A setback substation as an equipment fault",
    "R4-smooth-efficiency": "fits a smooth efficiency curve; runs the supply 25 K hotter",
    "R5-weather-attribution": "attributes fuel rise to weather; keeps B2 first in the window",
    "R6-trusts-streams": "never checks sequence numbers or uptime counters",
    "R7-logged-points": "fits the censored far-branch points for the saturation flow",
    "R8-no-npsh": "raises pump speed to 1.0 for the window without an NPSH check",
    "R9-ignores-tariff": "charges the tank from hour 40 to 62 regardless of the tariff",
    "one-at-a-time": "tunes one control at a time against a separable model",
    "no-monitoring-after-20": "stops reading telemetry and events after hour 20",
    "no-precharge": "never charges the tank",
    "blanket-safe": "conservative fixed settings for every seed, no experiments",
    "best-fixed-plan": "the best single plan across documented ranges, no discovery",
}

TAG_RTU = {}
for _t in (
    "TT-100",
    "TT-101",
    "FT-100",
    "FT-110",
    "FT-130",
    "PT-100",
    "LT-200",
    "JT-200",
    "SC-100",
    "TT-AMB",
):
    TAG_RTU[_t] = "RTU-PLANT"
for _t in ("JT-B1", "JT-B2", "JT-B3", "FQ-B1", "FQ-B2", "FQ-B3"):
    TAG_RTU[_t] = "RTU-BLR"
for _t in ("FT-120", "ZT-120"):
    TAG_RTU[_t] = "RTU-FAR"
for _s in M.SUBSTATIONS:
    for _p in ("TT-", "FT-", "JQ-"):
        TAG_RTU[_p + _s] = "RTU-" + _s

FAR_TT = ["TT-S4", "TT-S5", "TT-S6"]
PROBE_TS = 65.0
PROBE_FLOW = 245.0  # kg/s: the near call at 60 C plus any far saturation flow
PROBE_HOURS = 4.0
BASE_TS = 90.0
BASE_SPEED = 0.70
TS_MARGIN = 2.0
CHARGE = 14.0
# Raw tags read at the probe's load: far-branch returns, pump, branch and bypass flows, pump speed.
PROBE_RAW = FAR_TT + ["FT-100", "FT-110", "FT-130", "FT-120", "SC-100"]


class Telemetry:
    def __init__(self, packets: list[dict]):
        self.by_rtu: dict[str, list[dict]] = {}
        for pk in packets:
            self.by_rtu.setdefault(pk["rtu"], []).append(pk)

    def series(
        self, tag: str, lo: float = 0.0, hi: float = 1e9
    ) -> list[tuple[float, float]]:
        out = []
        for pk in self.by_rtu.get(TAG_RTU[tag], []):
            t = pk["interval_start_h"]
            v = pk["values"].get(tag)
            if v is not None and lo <= t < hi:
                out.append((t, v))
        return out

    def at(self, tag: str, t: float) -> float | None:
        for pk in self.by_rtu.get(TAG_RTU[tag], []):
            if pk["interval_start_h"] <= t < pk["interval_end_h"]:
                return pk["values"].get(tag)
        return None


class Operator:
    def __init__(self, client, variant: str = "reference"):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.c = client
        self.v = variant
        self.log: list[str] = []
        self.q_sat: float | None = None
        self.q_sat_censored: float | None = None
        self.q_osc: float | None = None
        self.q_nom = M.PUMP_RATED_FLOW
        self.b2_bad = False
        self.b2_onset: float | None = None
        self.incidents: list[dict] = []
        self.plan: dict = {}
        self.pending_tank: float | None = None
        self.fc: list[float] = []
        self.charge_boilers = ["B2", "B1", "B3"]

    # ------------------------------------------------------------------ helpers
    def note(self, text: str) -> None:
        self.log.append(text)

    def hour(self) -> float:
        return self.c.status()["plant_hour"]

    def change(self, at: float, change: dict) -> None:
        self.c.wait_until(at)
        st = self.c.status()
        if st["ramp_active"]:
            self.c.wait_until(
                st["plant_hour"] + st["ramp_remaining_s"] / 3600.0 + 0.003
            )
        if self.pending_tank is not None and "tank_rate" not in change:
            change = dict(change, tank_rate=self.pending_tank)
        self.pending_tank = None
        if self._reads(st["plant_hour"]):
            self.c.telemetry(max(0.0, st["plant_hour"] - 1.0))  # the plant before each change
        res = self.c.control(change)
        if not res.get("accepted"):
            raise RuntimeError(f"control rejected at {res.get('plant_hour')}: {res}")
        self.note(f"h{res['plant_hour']:.2f} change {change}")

    def telemetry(self) -> Telemetry:
        return Telemetry(self.c.telemetry(0.0)["packets"])

    # ------------------------------------------------------------------ reads only
    def _reads(self, hour: float) -> bool:
        """The no-monitoring variant reads nothing more after hour 20."""
        return not (self.v == "no-monitoring-after-20" and hour >= 20.0)

    def _raw_check(self, start: float) -> None:
        """10-second far-branch returns and pump flow over one past span (R1 never reads raw)."""
        if self.v == "R1-averaged-telemetry" or not self._reads(start):
            return
        self.c.wait_until(start + 0.5 + 0.003)
        self.c.raw(FAR_TT + ["FT-100"], start)

    def _post_ramp_read(self) -> None:
        """Telemetry once the last change's ramp has ended, before the graded window opens."""
        st = self.c.status()
        if not self._reads(st["plant_hour"]):
            return
        self.c.wait_until(st["plant_hour"] + st["ramp_remaining_s"] / 3600.0 + 0.003)
        self.c.telemetry(max(0.0, st["plant_hour"] - 1.0))

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        v = self.v
        self.fc = [
            row["ambient_c"] for row in self.c.forecast()["hourly_ambient_c"]
        ] + [None]
        self.fc[72] = self.fc[71]
        if v in ("blanket-safe", "best-fixed-plan"):
            return self._fixed_plan()
        probe = v != "R2-mild-extrapolation"
        charge_first = v not in ("R9-ignores-tariff", "no-precharge")
        first: dict = {"boilers": ["B2", "B1", "B3"]}
        if charge_first:
            first["tank_rate"] = CHARGE
        self.change(0.02, first)
        t = 0.02
        if probe:
            t = self._saturation_probe(0.36)
        if v not in ("R1-averaged-telemetry",):
            t = self._hunt_bisection(t)
        else:
            t = max(t, 0.5)
            self.change(t + 0.4, {"supply_temp": BASE_TS, "pump_speed": BASE_SPEED})
            t += 0.4
        self._schedule_tank_stop(6.0, t)
        self._first_day_checks()
        self._charging()
        self._window()
        if v != "no-monitoring-after-20":
            self._monitor()
        self.c.wait_until(72.0)
        return {
            "variant": v,
            "incidents": self.report(),
            "plan": self.plan,
            "log": self.log,
            "self_check": self.self_check(),
        }

    # ------------------------------------------------------------------ experiments
    def _saturation_probe(self, t0: float) -> float:
        """High-load probe: a low supply temperature drives the far valve to saturation."""
        self.c.wait_until(t0)
        tel = self.telemetry()
        self.q_nom = statistics.fmean(f / sp for (_, f), (_, sp) in zip(tel.series("FT-100"), tel.series("SC-100")))
        level = tel.series("LT-200")[-1][1] / 100.0
        speed = min(_safe_speed(level), PROBE_FLOW / self.q_nom, 1.0)
        self.change(t0, {"supply_temp": PROBE_TS, "pump_speed": round(speed, 4)})
        self.c.wait_until(t0 + PROBE_HOURS)
        tel = self.telemetry()
        if self.v != "R1-averaged-telemetry":
            self.c.raw(PROBE_RAW, t0 + 3.0)  # samples at the probe's load, after its ramp
        q = []
        for (ta, fp), (_, fn), (_, fb) in zip(
            tel.series("FT-100", t0 + PROBE_HOURS - 0.75, t0 + PROBE_HOURS),
            tel.series("FT-110", t0 + PROBE_HOURS - 0.75, t0 + PROBE_HOURS),
            tel.series("FT-130", t0 + PROBE_HOURS - 0.75, t0 + PROBE_HOURS),
        ):
            q.append(fp - fn - fb)
        self.q_sat = statistics.fmean(q[-2:])
        spd = tel.series("SC-100", t0 + 0.5, t0 + PROBE_HOURS)
        fp = tel.series("FT-100", t0 + 0.5, t0 + PROBE_HOURS)
        self.q_nom = statistics.fmean(
            f / s for (_, f), (_, s) in zip(fp, spd) if s > 0.1
        )
        self.note(
            f"saturation flow by mass balance {self.q_sat:.2f} kg/s; rated flow {self.q_nom:.1f}"
        )
        if self.v == "R7-logged-points":
            logged = []
            for k in range(int(PROBE_HOURS / 0.5) - 1):
                start = t0 + 0.25 + 0.5 * k
                logged.extend(x[1] for x in self.c.raw(["FT-120"], start)["samples"]["FT-120"])
            if logged:
                self.q_sat = max(logged)
                self.note(f"saturation flow from logged points {self.q_sat:.2f}")
        return t0 + PROBE_HOURS

    def _hunt_bisection(self, t0: float) -> float:
        lo, hi = 160.0, 240.0
        t = max(t0, 0.3)
        self.c.wait_until(t)
        tel = self.telemetry()
        pairs = [(f, sp) for (_, f), (_, sp) in zip(tel.series("FT-100"), tel.series("SC-100")) if sp > 0.1]
        self.q_nom = statistics.fmean(f / sp for f, sp in pairs[-4:])
        for _ in range(9):
            target = 0.5 * (lo + hi)
            self.c.wait_until(t)
            level = self.telemetry().series("LT-200")[-1][1] / 100.0
            speed = min(target / self.q_nom, _safe_speed(level))
            change = {"pump_speed": round(speed, 4)}
            if t <= PROBE_HOURS + 0.1:
                change["supply_temp"] = BASE_TS
            if t >= 6.0 and self.v not in ("R9-ignores-tariff", "no-precharge"):
                change["tank_rate"] = 0.0
            self.change(t, change)
            start = self.hour() + 0.40
            self.c.wait_until(start + 0.5 + 0.003)
            raw = self.c.raw(FAR_TT + ["FT-100"], start)["samples"]
            q_meas = statistics.fmean(x[1] for x in raw["FT-100"])
            hunting = False
            for tag in FAR_TT:
                vals = [x[1] for x in raw[tag]]
                diffs = [b - a for a, b in zip(vals, vals[1:])]
                rms = (sum(d * d for d in diffs) / len(diffs)) ** 0.5
                hunting = hunting or rms > 0.5
            if hunting:
                hi = min(hi, q_meas)
            else:
                lo = max(lo, q_meas)
            t = self.hour() + 0.02
        self.q_osc = 0.5 * (lo + hi)
        self.note(f"hunt threshold between {lo:.2f} and {hi:.2f} kg/s")
        self.change(t, {"pump_speed": BASE_SPEED})
        return t

    def _schedule_tank_stop(self, at: float, t: float) -> None:
        if self.v in ("R9-ignores-tariff", "no-precharge"):
            return
        if t < at:
            self.change(at, {"tank_rate": 0.0})

    # ------------------------------------------------------------------ evidence
    def _first_day_checks(self) -> None:
        """Per-boiler energy balance around the logged B2 fault code."""
        self.c.wait_until(20.0)
        ev = self.c.events(0.0)["events"]
        fault = [
            e for e in ev if e.get("event") == "fault_code" and e.get("subject") == "B2"
        ]
        if not fault or self.v == "R5-weather-attribution":
            return
        h = fault[0]["hour"]
        tel = self.telemetry()

        def eff(lo, hi):
            jt = tel.series("JT-B2", lo, hi)
            fq = tel.series("FQ-B2", lo, hi)
            pairs = [(a, b) for (_, a), (_, b) in zip(jt, fq) if b > 0.5]
            return statistics.fmean(a / b for a, b in pairs) if pairs else None

        before, after = eff(h - 3.0, h), eff(h + 0.5, h + 3.5)
        if before and after and after < 0.95 * before:
            self.b2_bad = True
            self.b2_onset = h
            self.charge_boilers = ["B1", "B3", "B2"]
            self.note(
                f"B2 efficiency {before:.3f} -> {after:.3f} after fault code at h{h:.2f}"
            )

    def _charging(self) -> None:
        v = self.v
        if v == "no-precharge":
            return
        if v == "R9-ignores-tariff":
            self.change(40.0, {"tank_rate": CHARGE, "boilers": ["B1", "B3", "B2"]})
            self.change(62.0, {"tank_rate": 0.0})
            return
        self.change(24.02, {"tank_rate": CHARGE, "boilers": self.charge_boilers})
        self.change(30.0, {"tank_rate": 0.0})
        self._raw_check(36.0)
        self.change(48.02, {"tank_rate": CHARGE, "boilers": self.charge_boilers})
        self.change(54.0, {"tank_rate": 0.0})

    # ------------------------------------------------------------------ window
    def _window(self) -> None:
        v = self.v
        self.c.wait_until(60.9)
        sat = None if v in ("R2-mild-extrapolation", "one-at-a-time") else self.q_sat
        ts_w = D.supply_for(self.fc, sat) + TS_MARGIN
        # one-at-a-time: supply tuned alone for the near floor, then flow tuned alone at that supply
        if v == "R4-smooth-efficiency":
            ts_w += 25.0
        need = D.flow_need(self.fc, ts_w, sat)
        if v == "R1-averaged-telemetry" or self.q_osc is None:
            q_w = 1.04 * need
        else:
            q_w = min(1.04 * need, 0.995 * self.q_osc)
        q_w = min(q_w, 0.90 * self.q_nom)
        speed = round(q_w / self.q_nom, 4)
        if v == "R8-no-npsh":
            speed = 1.0
        self.change(
            61.0, {"supply_temp": round(min(ts_w, 120.0), 2), "pump_speed": speed}
        )
        self._raw_check(62.0)
        boilers = ["B1", "B3"] if self.b2_bad else ["B2", "B1", "B3"]
        if v in ("no-precharge", "one-at-a-time"):
            boilers = ["B2", "B1", "B3"]
        self.c.wait_until(65.45)
        level = self.telemetry().series("LT-200", 64.0)[-1][1] / 100.0
        floor = D.tank_floor(0.90)
        if v == "R8-no-npsh":
            floor = 0.10
        rate = 0.0
        if v != "no-precharge":
            rate = max(0.0, min(M.TANK_MWH * (level - floor) / 6.3, 14.0))
        self.change(65.5, {"boilers": boilers, "tank_rate": -round(rate, 2)})
        self._post_ramp_read()
        self.plan = {
            "supply_temp": round(ts_w, 2),
            "pump_speed": speed,
            "boilers": boilers,
            "tank_rate": -round(rate, 2),
            "flow_need": round(need, 2),
            "tank_floor": round(floor, 3),
            "q_sat": self.q_sat,
            "q_osc": self.q_osc,
        }

    # ------------------------------------------------------------------ monitoring and D2
    def _monitor(self) -> None:
        self.c.wait_until(62.0)

    def _ratios(
        self, tel: Telemetry, k: int, lo: float, hi: float
    ) -> list[tuple[float, float]]:
        name = M.SUBSTATIONS[k]
        jq = dict(tel.series("JQ-" + name, lo, hi))
        ft = dict(tel.series("FT-" + name, lo, hi))
        tt = dict(tel.series("TT-" + name, lo, hi))
        ts = dict(tel.series("TT-100", max(0.0, lo - 3.5), hi))
        qp = dict(tel.series("FT-100", max(0.0, lo - 3.5), hi))
        qn = dict(tel.series("FT-110", max(0.0, lo - 3.5), hi))
        qb = dict(tel.series("FT-130", max(0.0, lo - 3.5), hi))
        out = []
        for t in sorted(jq):
            if t not in ft or t not in tt:
                continue
            if k in M.NEAR:
                tau = M.NEAR_TRANSPORT_H
            else:
                qf = qp.get(t, 0.0) - qn.get(t, 0.0) - qb.get(t, 0.0)
                tau = D.far_tau(max(qf, 1.0))
            src = round((t - tau) * 4.0) / 4.0
            if src not in ts:
                continue
            ta = ts[src] - M.SUPPLY_LOSS * (ts[src] - 8.0) * tau
            dt = ta - tt[t]
            if ft[t] <= 1.0 or dt <= 2.0:
                continue
            out.append((t, jq[t] / (M.C_W * ft[t] * dt)))
        return out

    def report(self) -> list[dict]:
        v = self.v
        horizon = 20.0 if v == "no-monitoring-after-20" else 60.5
        tel = Telemetry(
            [
                pk
                for pk in self.c.telemetry(0.0)["packets"]
                if pk["interval_end_h"] <= horizon
            ]
        )
        events = [e for e in self.c.events(0.0)["events"] if e["hour"] <= horizon]
        found: list[dict] = []
        excluded: dict[int, float] = {}
        # replaying RTU: a sequence number that does not increase
        if v != "R6-trusts-streams":
            for rtu, pks in tel.by_rtu.items():
                for a, b in zip(pks, pks[1:]):
                    if b["seq"] <= a["seq"]:
                        found.append(
                            {
                                "kind": "sensor",
                                "subject": rtu,
                                "onset_hour": b["interval_start_h"],
                                "value": None,
                            }
                        )
                        if rtu.startswith("RTU-S"):
                            excluded[M.SUBSTATIONS.index(rtu[4:])] = b[
                                "interval_start_h"
                            ]
                        break
        # firmware unit change on a substation flow meter
        for e in events:
            if e.get("event") == "firmware_update" and str(
                e.get("subject", "")
            ).startswith("RTU-S"):
                name = e["subject"][4:]
                before = [
                    x for _, x in tel.series("FT-" + name, e["hour"] - 3.0, e["hour"])
                ]
                after = [
                    x
                    for _, x in tel.series(
                        "FT-" + name, e["hour"] + 0.25, e["hour"] + 3.0
                    )
                ]
                if (
                    before
                    and after
                    and 3.0 < statistics.median(after) / statistics.median(before) < 4.4
                ):
                    found.append(
                        {
                            "kind": "sensor",
                            "subject": "FT-" + name,
                            "onset_hour": round(e["hour"], 3),
                            "value": None,
                        }
                    )
                    k = M.SUBSTATIONS.index(name)
                    excluded[k] = min(excluded.get(k, 1e9), e["hour"])
        # biased heat meter: substation energy balance in the first day
        bias_k = None
        dev = {}
        for k in range(6):
            r = [
                x
                for t, x in self._ratios(tel, k, 4.0, 20.0)
                if t < excluded.get(k, 1e9)
            ]
            if len(r) >= 8:
                dev[k] = statistics.median(r) - 1.0
        if dev:
            k = max(dev, key=lambda j: abs(dev[j]))
            if abs(dev[k]) > 0.05:
                bias_k = k
                found.append(
                    {
                        "kind": "sensor",
                        "subject": "JQ-" + M.SUBSTATIONS[k],
                        "onset_hour": 0.0,
                        "value": None,
                    }
                )
        # drifting heat meter: a hinge in the energy-balance ratio
        if horizon > 24.0:
            best = None
            for k in range(6):
                if k == bias_k:
                    continue
                pts = [
                    (t, x)
                    for t, x in self._ratios(tel, k, 12.0, horizon)
                    if t < excluded.get(k, 1e9)
                ]
                if len(pts) < 40:
                    continue
                fit = _hinge(pts)
                if (
                    fit
                    and abs(fit["slope"]) > 0.003
                    and (best is None or fit["gain"] > best[1]["gain"])
                ):
                    best = (k, fit)
            if best:
                found.append(
                    {
                        "kind": "sensor",
                        "subject": "JQ-" + M.SUBSTATIONS[best[0]],
                        "onset_hour": round(best[1]["onset"], 2),
                        "value": None,
                    }
                )
        if self.b2_bad and self.b2_onset is not None and self.b2_onset <= horizon:
            found.append(
                {
                    "kind": "equipment",
                    "subject": "B2",
                    "onset_hour": round(self.b2_onset, 3),
                    "value": None,
                }
            )
        decoy = M.SUBSTATIONS[M.DEEP_SETBACK]
        if v == "R3-setback-as-fault":
            found.append(
                {
                    "kind": "equipment",
                    "subject": decoy,
                    "onset_hour": 0.5,
                    "value": None,
                }
            )
        else:
            found.append(
                {
                    "kind": "contract",
                    "subject": decoy,
                    "onset_hour": None,
                    "value": None,
                }
            )
        if self.q_osc is not None:
            found.append(
                {
                    "kind": "operating_limit",
                    "subject": "FT-100",
                    "onset_hour": None,
                    "value": round(self.q_osc, 2),
                }
            )
        if self.q_sat is not None and v != "R2-mild-extrapolation":
            found.append(
                {
                    "kind": "operating_limit",
                    "subject": "FT-120",
                    "onset_hour": None,
                    "value": round(self.q_sat, 2),
                }
            )
        self.incidents = found
        return found

    # ------------------------------------------------------------------ fixed plans
    def _fixed_plan(self) -> dict:
        v = self.v
        if v == "blanket-safe":
            ts, speed = 104.0, 0.72
        else:
            ts, speed = 93.0, 0.745
        self.change(0.02, {"tank_rate": CHARGE, "boilers": ["B1", "B3", "B2"]})
        self.change(6.0, {"tank_rate": 0.0})
        self.change(24.02, {"tank_rate": CHARGE})
        self.change(30.0, {"tank_rate": 0.0})
        self.change(48.02, {"tank_rate": CHARGE})
        self.change(54.0, {"tank_rate": 0.0})
        self.change(61.0, {"supply_temp": ts, "pump_speed": speed})
        boilers = ["B1", "B3", "B2"] if v == "blanket-safe" else ["B1", "B3"]
        self.change(65.5, {"boilers": boilers, "tank_rate": -12.5})
        self.c.wait_until(72.0)
        found = [
            {
                "kind": "contract",
                "subject": M.SUBSTATIONS[M.DEEP_SETBACK],
                "onset_hour": None,
                "value": None,
            }
        ]
        self.incidents = found
        return {
            "variant": v,
            "incidents": found,
            "plan": {"supply_temp": ts, "pump_speed": speed},
            "log": self.log,
            "self_check": {},
        }

    # ------------------------------------------------------------------ self-check
    def self_check(self) -> dict:
        """Compliance as the policy itself sees it: its plan under its own beliefs, and the
        15-minute averages it reads."""
        v = self.v
        fc = self.fc
        demand = D.window_heat(fc)
        p = self.plan
        sat = None if v in ("R2-mild-extrapolation", "one-at-a-time") else self.q_sat
        deliverable = demand
        if sat is not None:
            ts = p["supply_temp"]
            far_cap = 0.0
            for h in D.WINDOW_HOURS:
                lf = sum(D.load(fc, h, k) for k in M.FAR)
                tsf = (
                    sum(D.load(fc, h, k) * D.tsec(k, D.load(fc, h, k)) for k in M.FAR)
                    / lf
                )
                taf = ts - M.SUPPLY_LOSS * (ts - 8.0) * D.far_tau(sat)
                far_cap += min(lf, M.EPS_HX * M.C_W * sat * (taf - tsf))
            near = sum(D.load(fc, h, k) for h in D.WINDOW_HOURS for k in M.NEAR)
            deliverable = min(demand, near + far_cap)
        capacity = (
            6.0 * (sum(M.BOILER_CAP[b] for b in p["boilers"]) - 1.0)
            - 6.0 * p["tank_rate"]
        )
        if v == "no-precharge" or v == "one-at-a-time":
            capacity = 6.0 * sum(M.BOILER_CAP[b] for b in ("B1", "B2", "B3"))
        heat = (
            min(deliverable, capacity)
            if v not in ("no-precharge", "one-at-a-time")
            else min(deliverable, demand)
        )
        tel = self.telemetry()
        avg_min = min(
            (
                x
                for k in range(6)
                for _, x in tel.series("TT-" + M.SUBSTATIONS[k], 66.0, 72.0)
            ),
            default=99.0,
        )
        return {
            "O1_predicted_mwh": round(heat, 2),
            "O1": heat >= M.CONTRACTED_MWH,
            "O2_min_15min_return": round(avg_min, 2),
            "O2": avg_min >= 55.0 if v == "R1-averaged-telemetry" else True,
            "O3": True,
            "O4": True,
        }


def _hinge(pts: list[tuple[float, float]]) -> dict | None:
    ts = [t for t, _ in pts]
    xs = [x for _, x in pts]
    base = statistics.fmean(xs)
    sse0 = sum((x - base) ** 2 for x in xs)
    best = None
    t0 = ts[0] + 2.0
    while t0 < ts[-1] - 2.0:
        pre = [x for t, x in pts if t < t0]
        r0 = statistics.fmean(pre) if pre else base
        num = sum((x - r0) * (t - t0) for t, x in pts if t >= t0)
        den = sum((t - t0) ** 2 for t, _ in pts if t >= t0)
        a = num / den if den > 0 else 0.0
        sse = sum((x - r0) ** 2 for t, x in pts if t < t0) + sum(
            (x - r0 - a * (t - t0)) ** 2 for t, x in pts if t >= t0
        )
        if best is None or sse < best["sse"]:
            best = {
                "onset": t0,
                "slope": a / max(r0, 1e-6),
                "sse": sse,
                "gain": sse0 - sse,
            }
        t0 += 0.25
    return best


def _safe_speed(level: float) -> float:
    """Highest pump speed whose NPSH margin the tank level still covers (datasheet)."""
    speed = 1.0
    while speed > 0.3 and D.tank_floor(speed, 50.0) > level:
        speed -= 0.005
    return speed
