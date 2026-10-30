"""Verifier reference static timing analysis over the generator's structured model.

Liberty NLDM lookup with linear extrapolation, SDC clocks and exceptions, graph-based late and early
propagation keyed by launching clock edge and exception state, CPPR at the last common clock pin,
level-sensitive latch borrowing, and OCV cell-delay derates. Times are in ns internally.
"""

import math
import sys
from fractions import Fraction

sys.setrecursionlimit(20000)
LIB_TIME = {"1ps": 1e-3, "1ns": 1.0}
LIB_CAP = {"ff": 1e-3, "pf": 1.0}
SDC_TIME = {"ns": 1.0, "ps": 1e-3}
SDC_CAP = {"pF": 1.0, "fF": 1e-3}
TIME_VARS = {
    "input_net_transition",
    "constrained_pin_transition",
    "related_pin_transition",
}
TRS = ("rise", "fall")
OPP = {"rise": "fall", "fall": "rise"}
MCP_SETUP, MCP_HOLD = "mcp_setup", "mcp_hold"
LATCH_MASTER_EDGE, CREDIT_OPPOSITE = "latch-master-edge", "credit-opposite"
# Targeting variants: alternative readings that pick_case uses to confirm a hidden case discriminates.
TIE_LARGER, BORROW_UNBOUNDED, GEN_AS_MASTER = (
    "tie-larger",
    "borrow-unbounded",
    "gen-as-master",
)
IDEAL_SETUP_SLEW0, IDEAL_HOLD_SLEW0 = "ideal-setup-slew0", "ideal-hold-slew0"
CAPTURE_IN_LAUNCH_MODE = "capture-in-launch-mode"
HOLD_UNSHIFTED = "hold-unshifted"
GEN_NEAR_SOURCE = "gen-near-source"
MCP_INTEGER_RATIO = "mcp-integer-ratio"
LATCH_CHAIN_NO_THROUGH_D = "latch-chain-no-through-d"
LATCH_GEN_NO_CPPR = "latch-gen-no-cppr"
HOLD_CAPTURE_PERIOD = "hold-capture-period"
PBA_GRAPH_SLEW = "pba-graph-slew"
PBA_NO_DERATE = "pba-no-derate"
INPUT_MIN_IGNORED = "input-min-ignored"
OUTPUT_DELAY_ADDED = "output-delay-added"
PBA_COUNT = 5
SENSE = {
    "positive_unate": lambda tr: [tr],
    "negative_unate": lambda tr: [OPP[tr]],
    "non_unate": lambda tr: ["fall", "rise"],
}


def frac(x) -> Fraction:
    return Fraction(format(x, ".10g"))


def flcm(a: Fraction, b: Fraction) -> Fraction:
    p, q = a.numerator * b.denominator, b.numerator * a.denominator
    return Fraction(p * q // math.gcd(p, q), a.denominator * b.denominator)


class Ref:
    def __init__(self, lib, netlist, cons, variant=None):
        self.variant = variant
        self.lib, self.nl, self.cons = lib, netlist, cons
        self.ts, self.cs = LIB_TIME[lib["time_unit"]], LIB_CAP[lib["cap_unit"]]
        self.sts, self.scs = (
            SDC_TIME[cons["units"]["time"]],
            SDC_CAP[cons["units"]["cap"]],
        )
        self.extrap = 0
        self.gaps = []
        self.opp = []
        self.cdepth = []
        self.extrap_vars = set()
        self.used_templates = set()
        self._darr = {}
        self._carr = {}
        self._load = {}
        self._rel = {}
        # Exact data-merge ties whose candidates have different predecessors, and the data nodes a
        # report value reads through its predecessor chain (CPPR launch traces and S22 paths).
        self.ties = {"late": set(), "early": set()}
        self.traced = {"late": set(), "early": set()}
        self.pba_gaps = []
        self._netlist()
        self.f = {
            ("late", "data"): 1.0,
            ("early", "data"): 1.0,
            ("late", "clock"): 1.0,
            ("early", "clock"): 1.0,
        }
        for d in cons["derates"]:
            self.f[(d["which"], d["where"])] = d["factor"]
        self._clocks()
        self.ex = [
            {
                "kind": e["kind"],
                "n": e.get("n", 1),
                "from": {tuple(x) for x in e.get("from", [])},
                "through": set(e.get("through", [])),
                "to": {tuple(x) for x in e.get("to", [])},
            }
            for e in cons["exceptions"]
        ]

    # ---------------------------------------------------------------- library lookups
    def table(self, entry, point):
        tname, vals = entry
        t = self.lib["templates"][tname]
        xs, idx = [], []
        self.used_templates.add(tname)
        v = t["vars"]
        for var, index in zip(t["vars"], t["index"]):
            scale = self.ts if var in TIME_VARS else self.cs
            idx.append([v * scale for v in index])
            xs.append(point[var])
        if len(idx) == 1:
            return self._interp(idx[0], [x * self.ts for x in vals], xs[0], v[0])
        rows = [
            self._interp(idx[1], [x * self.ts for x in row], xs[1], v[1])
            for row in vals
        ]
        return self._interp(idx[0], rows, xs[0], v[0])

    def _interp(self, index, values, x, var=None):
        n = len(index)
        if n == 1:
            return values[0]
        if x < index[0] or x > index[-1]:
            self.extrap += 1
            self.extrap_vars.add(var)
        if x <= index[0]:
            k = 0
        elif x >= index[-1]:
            k = n - 2
        else:
            k = max(i for i in range(n - 1) if index[i] <= x)
        return values[k] + (values[k + 1] - values[k]) * (x - index[k]) / (
            index[k + 1] - index[k]
        )

    def wire_cap(self, fanout):
        if fanout == 0:
            return 0.0
        w = self.lib["wire_load"]
        pts = sorted(w["fanout_length"])
        fs = [p[0] for p in pts]
        if fanout in fs:
            length = pts[fs.index(fanout)][1]
        elif fanout > fs[-1]:
            length = pts[-1][1] + w["slope"] * (fanout - fs[-1])
        else:
            lo = max(p for p in pts if p[0] < fanout)
            hi = min(p for p in pts if p[0] > fanout)
            length = lo[1] + (hi[1] - lo[1]) * (fanout - lo[0]) / (hi[0] - lo[0])
        return length * w["capacitance"] * self.cs

    # ---------------------------------------------------------------- netlist graph
    def _netlist(self):
        self.inst = {i["name"]: i for i in self.nl["insts"]}
        self.driver, self.sinks, self.outports, self.net_of = {}, {}, {}, {}
        for p in self.nl["inputs"]:
            self.driver[p] = p
            self.net_of[p] = p
        for i in self.nl["insts"]:
            cell = self.lib["cells"][i["cell"]]
            for pin, net in i["conns"].items():
                full = f"{i['name']}/{pin}"
                self.net_of[full] = net
                if cell["pins"][pin]["direction"] == "output":
                    self.driver[net] = full
                else:
                    self.sinks.setdefault(net, []).append(full)
        for port, net in self.nl["assigns"].items():
            self.outports.setdefault(net, []).append(port)
            self.net_of[port] = net

    def cell_of(self, pin):
        return self.lib["cells"][self.inst[pin.split("/")[0]]["cell"]]

    def load(self, net):
        if net not in self._load:
            sinks = self.sinks.get(net, [])
            ports = self.outports.get(net, [])
            c = sum(
                self.cell_of(s)["pins"][s.split("/")[1]]["capacitance"] * self.cs
                for s in sinks
            )
            c += sum(self.cons["load"].get(p, 0.0) * self.scs for p in ports)
            self._load[net] = c + self.wire_cap(len(sinks) + len(ports))
        return self._load[net]

    def arcs_to(self, pin):
        p = pin.split("/")[1]
        return [
            t
            for t in self.cell_of(pin)["timing"]
            if t["pin"] == p and t["timing_type"] in ("combinational", "rising_edge")
        ]

    def check_on(self, pin, prefix):
        p = pin.split("/")[1]
        return next(
            t
            for t in self.cell_of(pin)["timing"]
            if t["pin"] == p and t["timing_type"].startswith(prefix)
        )

    def arc_eval(self, arc, tr, slew, load, factor):
        pt = {"input_net_transition": slew, "total_output_net_capacitance": load}
        return self.table(arc["tables"][f"cell_{tr}"], pt) * factor, self.table(
            arc["tables"][f"{tr}_transition"], pt
        )

    # ---------------------------------------------------------------- clocks
    def _clocks(self):
        c = self.cons
        st = frac(self.sts)
        self.clock = {}
        for k in c["clocks"]:
            self.clock[k["name"]] = {
                "P": frac(k["period"]) * st,
                "rise": frac(k["waveform"][0]) * st,
                "fall": frac(k["waveform"][1]) * st,
            }
        self.clock_of, self.clock_pins, self.seq_clock_pins = {}, set(), set()
        self.root_ports = {k["port"]: k for k in c["clocks"]}
        self.gen_pins = {g["pin"]: g for g in c["generated"]}
        for k in c["clocks"]:
            self._mark(k["port"], k["name"])
        for g in c["generated"]:
            self._mark(g["pin"], g["name"])
            m = self.clock[self.clock_of[g["source_pin"]]]
            P, r, f = m["P"], m["rise"], m["fall"]
            if self.variant == GEN_AS_MASTER:
                self.clock[g["name"]] = dict(m)
                continue
            if "multiply_by" in g:
                k = g["multiply_by"]
                self.clock[g["name"]] = {"P": P / k, "rise": r, "fall": r + (f - r) / k}
            else:
                edges = (
                    g["edges"]
                    if "edges" in g
                    else [1, g["divide_by"] + 1, 2 * g["divide_by"] + 1]
                )

                def at(e):
                    return (r if e % 2 == 1 else f) + ((e - 1) // 2) * P

                self.clock[g["name"]] = {
                    "P": at(edges[2]) - at(edges[0]),
                    "rise": at(edges[0]),
                    "fall": at(edges[1]),
                }
        self.propagated = c["propagated"] == "all"
        self.gen_master = {
            g["name"]: self.clock_of[g["source_pin"]] for g in c["generated"]
        }
        self.near_stop = {
            g["source_pin"]
            for g in c["generated"]
            if self.gen_master[g["name"]] in self.gen_master
        }

    def _mark(self, root, clock):
        stack = [root]
        self.clock_pins.add(root)
        self.clock_of[root] = clock
        while stack:
            pin = stack.pop()
            for s in self.sinks.get(self.net_of[pin], []):
                cell = self.cell_of(s)
                p = s.split("/")[1]
                self.clock_pins.add(s)
                self.clock_of[s] = clock
                if cell["pins"][p].get("clock"):
                    self.seq_clock_pins.add(s)
                    continue
                for t in cell["timing"]:
                    if t["related_pin"] == p and t["timing_type"] == "combinational":
                        out = f"{s.split('/')[0]}/{t['pin']}"
                        self.clock_pins.add(out)
                        self.clock_of[out] = clock
                        stack.append(out)

    def carr(self, pin, tr):
        """Clock arrival record {'src', 'late': (a, slew, pred), 'early': (...)} relative to the triggering source edge."""
        key = (pin, tr)
        if key in self._carr:
            return self._carr[key]
        if pin in self.root_ports:
            s = self.cons["input_transition"].get(pin, 0.0) * self.sts
            rec = {"src": tr, "late": (0.0, s, None), "early": (0.0, s, None)}
        elif pin in self.gen_pins:
            ck = self.gen_pins[pin]["source_pin"]
            arc = self.arcs_to(pin)[0]
            load = self.load(self.net_of[pin])
            cin = self.carr(ck, "rise")
            rec = {"src": tr}
            for mode in ("late", "early"):
                d, sl = self.arc_eval(
                    arc, tr, cin[mode][1], load, self.f[(mode, "clock")]
                )
                rec[mode] = (cin[mode][0] + d, sl, (ck, "rise"))
        elif self.cell_of(pin)["pins"][pin.split("/")[1]]["direction"] == "input":
            drv = self.driver[self.net_of[pin]]
            src = self.carr(drv, tr)
            rec = {
                "src": src["src"],
                "late": (src["late"][0], src["late"][1], (drv, tr)),
                "early": (src["early"][0], src["early"][1], (drv, tr)),
            }
        else:
            load = self.load(self.net_of[pin])
            inst = pin.split("/")[0]
            cands = []
            for arc in self.arcs_to(pin):
                inp = f"{inst}/{arc['related_pin']}"
                for itr in SENSE[arc["timing_sense"]](tr):
                    cin = self.carr(inp, itr)
                    row = {"src": cin["src"]}
                    for mode in ("late", "early"):
                        d, sl = self.arc_eval(
                            arc, tr, cin[mode][1], load, self.f[(mode, "clock")]
                        )
                        row[mode] = (cin[mode][0] + d, sl, (inp, itr))
                    cands.append(row)
            rec = {"src": cands[0]["src"]}
            for mode, pick in (("late", max), ("early", min)):
                best = pick(c[mode][0] for c in cands)
                win = (max if self.variant == TIE_LARGER else min)(
                    (c for c in cands if c[mode][0] == best), key=lambda c: c[mode][2]
                )
                others = [c[mode][0] for c in cands if c[mode][2] != win[mode][2]]
                if others:
                    self.gaps.append(min(abs(best - o) for o in others))
                rec[mode] = (best, pick(c[mode][1] for c in cands), win[mode][2])
        self._carr[key] = rec
        return rec

    def clk_info(self, pin, tr):
        clock = self.clock_of[pin]
        rec = self.carr(pin, tr)
        if self.propagated:
            return (
                clock,
                rec["src"],
                {m: rec[m][0] for m in ("late", "early")},
                {m: rec[m][1] for m in ("late", "early")},
            )
        s = self.cons["clock_transition"].get(clock, 0.0) * self.sts
        return clock, rec["src"], {"late": 0.0, "early": 0.0}, {"late": s, "early": s}

    def ctrace(self, pin, tr, mode):
        out, cur = [], (pin, tr)
        stop = self.near_stop if self.variant == GEN_NEAR_SOURCE else ()
        while cur is not None:
            out.append(cur)
            if cur[0] in stop:
                break
            cur = self.carr(*cur)[mode][2]
        return out[::-1]

    def relation(self, lc, ltyp, cc, ctyp):
        key = (lc, ltyp, cc, ctyp)
        if key in self._rel:
            return self._rel[key]
        L, C = self.clock[lc], self.clock[cc]
        PL, PC = L["P"], C["P"]
        bl, bc = L[ltyp], C[ctyp]
        common = flcm(PL, PC)
        if self.variant == MCP_INTEGER_RATIO:
            common = max(PL, PC) // min(PL, PC) * min(PL, PC)
        best = None
        for k in range(max(1, int(common / PL))):
            l = bl + k * PL
            c = bc + (math.floor((l - bc) / PC) + 1) * PC
            if best is None or c - l < best:
                best = c - l
        self._rel[key] = (best, PL, PC)
        return best, PL, PC

    # ---------------------------------------------------------------- exceptions
    def start_tag(self, clock, edge, objs):
        pend, done = set(), set()
        for i, e in enumerate(self.ex):
            if not e["from"] or e["from"] & objs:
                (pend if e["through"] else done).add(i)
        return (clock, edge, frozenset(pend), frozenset(done))

    def step(self, tag, pin):
        moved = {i for i in tag[2] if pin in self.ex[i]["through"]}
        return tag if not moved else (tag[0], tag[1], tag[2] - moved, tag[3] | moved)

    def applicable(self, tag, objs):
        hits = [
            self.ex[i]
            for i in tag[3]
            if not self.ex[i]["to"] or self.ex[i]["to"] & objs
        ]
        if any(e["kind"] == "false" for e in hits):
            return None
        return (
            max([e["n"] for e in hits if e["kind"] == MCP_SETUP], default=1),
            max([e["n"] for e in hits if e["kind"] == MCP_HOLD], default=0),
        )

    # ---------------------------------------------------------------- data arrivals
    def _merge(self, slot, tag, row, key):
        cur = slot.get(tag)
        if cur is None:
            slot[tag] = list(row)
            return
        for ia, isl, ip, pick, mode in (
            (0, 1, 2, max, "late"),
            (3, 4, 5, min, "early"),
        ):
            a, b = cur[ia], row[ia]
            if a != b:
                self.gaps.append(abs(a - b))
            elif repr(row[ip]) != repr(cur[ip]) and not self._same_port(row[ip], cur[ip]):
                self.ties[mode].add((key[0], key[1], tag))
            if pick(a, b) != a or (a == b and repr(row[ip]) < repr(cur[ip])):
                cur[ia], cur[ip] = b, row[ip]
            cur[isl] = pick(cur[isl], row[isl])

    def _same_port(self, a, b):
        """Both candidates leave one pin fed straight from an input port, whose rise and fall arrivals
        and slews are equal, so either candidate traces the same pins with the same values."""
        if a[0] != b[0] or a[2] != b[2]:
            return False
        return a[0] in self.nl["inputs"] or self.driver.get(self.net_of.get(a[0])) in self.nl["inputs"]

    def darr(self, pin):
        if pin in self._darr:
            return self._darr[pin]
        res = {"rise": {}, "fall": {}}
        self._darr[pin] = res
        if "/" not in pin:
            if pin in self.nl["inputs"]:
                d = next(
                    (x for x in self.cons["input_delay"] if x["port"] == pin), None
                )
                if d is not None:
                    tag = self.start_tag(
                        d["clock"], "rise", {("port", pin), ("clock", d["clock"])}
                    )
                    s = self.cons["input_transition"].get(pin, 0.0) * self.sts
                    early = d["max"] if self.variant == INPUT_MIN_IGNORED else d["min"]
                    for tr in TRS:
                        res[tr][tag] = [
                            d["max"] * self.sts,
                            s,
                            None,
                            early * self.sts,
                            s,
                            None,
                        ]
            else:
                drv = self.driver[self.net_of[pin]]
                for tr in TRS:
                    for tag, r in self.darr(drv)[tr].items():
                        res[tr][tag] = [
                            r[0],
                            r[1],
                            (drv, tr, tag),
                            r[3],
                            r[4],
                            (drv, tr, tag),
                        ]
            return res
        inst, p = pin.split("/")
        cell = self.cell_of(pin)
        if cell["pins"][p]["direction"] == "input":
            drv = self.driver[self.net_of[pin]]
            for tr in TRS:
                for tag, r in self.darr(drv)[tr].items():
                    self._merge(
                        res[tr],
                        self.step(tag, pin),
                        [r[0], r[1], (drv, tr, tag), r[3], r[4], (drv, tr, tag)],
                        (pin, tr),
                    )
            return res
        load = self.load(self.net_of[pin])
        if "ff" in cell or "latch" in cell:
            ck = f"{inst}/{'CK' if 'ff' in cell else 'G'}"
            clock, src, lat, slew = self.clk_info(ck, "rise")
            tag = self.step(
                self.start_tag(clock, src, {("cell", inst), ("clock", clock)}), pin
            )
            arc = next(
                a for a in self.arcs_to(pin) if a["timing_type"] == "rising_edge"
            )
            for tr in TRS:
                row = []
                for mode in ("late", "early"):
                    d, sl = self.arc_eval(
                        arc, tr, slew[mode], load, self.f[(mode, "data")]
                    )
                    row += [lat[mode] + d, sl, ("clk", ck)]
                self._merge(res[tr], tag, row, (pin, tr))
            if "latch" in cell:
                darc = next(
                    a for a in self.arcs_to(pin) if a["timing_type"] == "combinational"
                )
                for tr, utag, a, s, shift in self.latch_borrowers(f"{inst}/D"):
                    if self.variant == LATCH_CHAIN_NO_THROUGH_D and self.through_latch(
                        f"{inst}/D", tr, utag
                    ):
                        continue
                    d, sl = self.arc_eval(darc, tr, s, load, self.f[("late", "data")])
                    la = a - shift + d
                    cur = res[tr][tag]
                    if la != cur[0]:
                        self.gaps.append(abs(la - cur[0]))
                    else:
                        self.ties["late"].add((pin, tr, tag))
                    if la > cur[0]:
                        cur[0], cur[2] = la, ("latchD", f"{inst}/D", tr, utag, shift)
                    cur[1] = max(cur[1], sl)
            return res
        for arc in self.arcs_to(pin):
            inp = f"{inst}/{arc['related_pin']}"
            ins = self.darr(inp)
            for tr in TRS:
                for itr in SENSE[arc["timing_sense"]](tr):
                    for tag, r in ins[itr].items():
                        dl, sl = self.arc_eval(
                            arc, tr, r[1], load, self.f[("late", "data")]
                        )
                        de, se = self.arc_eval(
                            arc, tr, r[4], load, self.f[("early", "data")]
                        )
                        self._merge(
                            res[tr],
                            self.step(tag, pin),
                            [
                                r[0] + dl,
                                sl,
                                (inp, itr, tag),
                                r[3] + de,
                                se,
                                (inp, itr, tag),
                            ],
                            (pin, tr),
                        )
        return res

    # ---------------------------------------------------------------- checks
    def launch_of(self, pin, tr, tag, mode):
        idx = 2 if mode == "late" else 5
        cur = (pin, tr, tag)
        seen = self.traced[mode]
        while True:
            seen.add(cur)
            pred = self.darr(cur[0])[cur[1]][cur[2]][idx]
            if pred is None:
                return None
            if pred[0] == "clk":
                return pred[1]
            if pred[0] == "latchD":
                return pred[1].split("/")[0] + "/G"
            cur = pred

    def through_latch(self, pin, tr, tag):
        cur = (pin, tr, tag)
        while True:
            pred = self.darr(cur[0])[cur[1]][cur[2]][2]
            if pred is None or pred[0] == "clk":
                return False
            if pred[0] == "latchD":
                return True
            cur = pred

    def credit(self, launch_pin, mode_l, cap_pin, cap_tr, mode_c):
        if not self.propagated or launch_pin is None:
            return 0.0
        tl = self.ctrace(launch_pin, "rise", mode_l)
        if self.variant == CAPTURE_IN_LAUNCH_MODE:
            mode_c = mode_l
        tc = dict(self.ctrace(cap_pin, cap_tr, mode_c))
        for depth in range(len(tl) - 1, -1, -1):
            pin, tr = tl[depth]
            if pin in tc:
                rec = self.carr(pin, tr)
                if tc[pin] != tr and self.variant != CREDIT_OPPOSITE:
                    self.opp.append(rec["late"][0] - rec["early"][0])
                    return 0.0
                if rec["late"][0] > rec["early"][0]:
                    self.cdepth.append(depth)
                return rec["late"][0] - rec["early"][0]
        return 0.0

    def _seq_check(self, dpin, tr, tag, r):
        """Returns (setup, hold, borrow, S) or None for a false path at a sequential data pin."""
        inst = dpin.split("/")[0]
        latch = "latch" in self.cell_of(dpin)
        ck = f"{inst}/{'G' if latch else 'CK'}"
        close_tr = "fall" if latch else "rise"
        clock, src_o, lat_o, _ = self.clk_info(ck, "rise")
        _, src_c, lat_c, slew_c = self.clk_info(ck, close_tr)
        nm = self.applicable(tag, {("pin", dpin), ("cell", inst), ("clock", clock)})
        if nm is None:
            return None
        lclk = tag[0]
        if self.variant == LATCH_MASTER_EDGE and latch and tag[0] in self.gen_master:
            lclk = self.gen_master[tag[0]]
        S, PL, PC = self.relation(lclk, tag[1], clock, src_o)
        S = S + (nm[0] - 1) * PC
        cr_s = self.credit(
            self.launch_of(dpin, tr, tag, "late"), "late", ck, "rise", "early"
        )
        cr_h = self.credit(
            self.launch_of(dpin, tr, tag, "early"), "early", ck, close_tr, "late"
        )
        if self.variant == LATCH_GEN_NO_CPPR and latch and clock in self.gen_master:
            cr_s = cr_h = 0.0
        su = self.table(
            self.check_on(dpin, "setup")["tables"][f"{tr}_constraint"],
            {
                "constrained_pin_transition": r[1],
                "related_pin_transition": 0.0
                if (self.variant == IDEAL_SETUP_SLEW0 and not self.propagated)
                else slew_c["early"],
            },
        )
        ho = self.table(
            self.check_on(dpin, "hold")["tables"][f"{tr}_constraint"],
            {
                "constrained_pin_transition": r[4],
                "related_pin_transition": 0.0
                if (self.variant == IDEAL_HOLD_SLEW0 and not self.propagated)
                else slew_c["late"],
            },
        )
        if latch:
            Sc, _, _ = self.relation(lclk, tag[1], clock, src_c)
            Sc = Sc + (nm[0] - 1) * PC
            bo, bc = self.clock[clock][src_o], self.clock[clock][src_c]
            W = bc + (math.floor((bo - bc) / PC) + 1) * PC - bo
            maxb = max(0.0, float(W) + lat_c["early"] - lat_o["early"] - su)
            base = float(S) + lat_o["early"] + cr_s
            if r[0] != base:
                self.gaps.append(abs(r[0] - base))
            borrow = max(0.0, r[0] - base)
            if self.variant != BORROW_UNBOUNDED:
                borrow = min(borrow, maxb)
            setup = base + borrow - r[0]
            H = Sc - self._hold_period(PL, PC) - nm[1] * PL
        else:
            borrow = None
            setup = float(S) + lat_o["early"] - su + cr_s - r[0]
            H = S - self._hold_period(PL, PC) - nm[1] * PL
            if self.variant == HOLD_UNSHIFTED and nm[1] == 0:
                H -= (nm[0] - 1) * PC
        hold = r[3] - (float(H) + lat_c["late"] + ho - cr_h)
        return setup, hold, borrow, float(S)

    def _hold_period(self, PL, PC):
        return PC if self.variant == HOLD_CAPTURE_PERIOD else min(PL, PC)

    def latch_borrowers(self, dpin):
        out = []
        for tr in TRS:
            for tag, r in self.darr(dpin)[tr].items():
                chk = self._seq_check(dpin, tr, tag, r)
                if chk is not None and chk[2] > 0:
                    out.append((tr, tag, r[0], r[1], chk[3]))
        return out

    def endpoint_checks(self, ep):
        out = []
        if "/" not in ep:
            d = next(x for x in self.cons["output_delay"] if x["port"] == ep)
            for tr in TRS:
                for tag, r in self.darr(ep)[tr].items():
                    nm = self.applicable(tag, {("port", ep), ("clock", d["clock"])})
                    if nm is None:
                        continue
                    S, PL, PC = self.relation(tag[0], tag[1], d["clock"], "rise")
                    S = S + (nm[0] - 1) * PC
                    H = S - self._hold_period(PL, PC) - nm[1] * PL
                    if self.variant == HOLD_UNSHIFTED and nm[1] == 0:
                        H -= (nm[0] - 1) * PC
                    sign = -1 if self.variant == OUTPUT_DELAY_ADDED else 1
                    out.append(
                        (
                            tr,
                            tag,
                            float(S) - sign * d["max"] * self.sts - r[0],
                            r[3] - (float(H) - d["min"] * self.sts),
                            None,
                        )
                    )
            return out
        for tr in TRS:
            for tag, r in self.darr(ep)[tr].items():
                chk = self._seq_check(ep, tr, tag, r)
                if chk is not None:
                    out.append((tr, tag, chk[0], chk[1], chk[2]))
        return out

    # ---------------------------------------------------------------- report
    def endpoints(self):
        ports = set(self.nl["outputs"])
        eps = [d["port"] for d in self.cons["output_delay"] if d["port"] in ports]
        for i in self.nl["insts"]:
            cell = self.lib["cells"][i["cell"]]
            if "ff" in cell or "latch" in cell:
                eps.append(f"{i['name']}/D")
        return sorted(set(eps))

    def analyse(self):
        report = {"endpoints": {}, "arrivals": {}, "borrow": {}}
        detail = {}
        for ep in self.endpoints():
            rows = self.endpoint_checks(ep)
            detail[ep] = rows
            report["endpoints"][ep] = {
                "setup": min((r[2] for r in rows), default=None),
                "hold": min((r[3] for r in rows), default=None),
            }
            if "/" in ep and "latch" in self.cell_of(ep):
                report["borrow"][ep] = max((r[4] for r in rows), default=None)
        setups = [
            v["setup"] for v in report["endpoints"].values() if v["setup"] is not None
        ]
        holds = [
            v["hold"] for v in report["endpoints"].values() if v["hold"] is not None
        ]
        report["wns_setup"] = min(setups) if setups else None
        report["tns_setup"] = sum(min(0.0, s) for s in setups)
        report["wns_hold"] = min(holds) if holds else None
        report["tns_hold"] = sum(min(0.0, s) for s in holds)
        pins = list(self.nl["inputs"]) + list(self.nl["outputs"])
        for i in self.nl["insts"]:
            pins += [f"{i['name']}/{p}" for p in i["conns"]]
        for pin in pins:
            if pin in self.clock_pins:
                continue
            arr = self.darr(pin)
            if not arr["rise"] and not arr["fall"]:
                continue
            report["arrivals"][pin] = {
                "late_rise": max((r[0] for r in arr["rise"].values()), default=None),
                "late_fall": max((r[0] for r in arr["fall"].values()), default=None),
                "early_rise": min((r[3] for r in arr["rise"].values()), default=None),
                "early_fall": min((r[3] for r in arr["fall"].values()), default=None),
            }
        report["pba_setup"] = self.pba(report, detail)
        return {
            k: report[k]
            for k in (
                "wns_setup",
                "tns_setup",
                "wns_hold",
                "tns_hold",
                "endpoints",
                "arrivals",
                "borrow",
                "pba_setup",
            )
        }

    def pba(self, report, detail):
        """S22: re-time the worst setup path of the PBA_COUNT worst register and port endpoints."""
        cands = sorted(
            (v["setup"], ep)
            for ep, v in report["endpoints"].items()
            if v["setup"] is not None and ("/" not in ep or "ff" in self.cell_of(ep))
        )
        if len(cands) > PBA_COUNT:
            self.pba_gaps.append(cands[PBA_COUNT][0] - cands[PBA_COUNT - 1][0])
        out = {}
        for _slack, ep in cands[:PBA_COUNT]:
            rows = sorted(
                (r for r in detail[ep] if r[2] is not None),
                key=lambda r: (r[2], r[0] != "rise", repr(r[1])),
            )
            if len(rows) > 1:
                self.pba_gaps.append(rows[1][2] - rows[0][2])
            tr, tag = rows[0][0], rows[0][1]
            out[ep] = self.pba_slack(ep, tr, tag, rows[0][2])
        return out

    def pba_path(self, ep, tr, tag):
        path, cur = [], (ep, tr, tag)
        while True:
            path.append(cur)
            pred = self.darr(cur[0])[cur[1]][cur[2]][2]
            if pred is None or pred[0] in ("clk", "latchD"):
                break
            cur = pred
        return path[::-1]

    def pba_slack(self, ep, tr, tag, graph_slack):
        if self.variant == PBA_GRAPH_SLEW:
            return graph_slack
        path = self.pba_path(ep, tr, tag)
        self.traced["late"].update(path)
        start = self.darr(path[0][0])[path[0][1]][path[0][2]]
        arrival, slew = start[0], start[1]
        factor = 1.0 if self.variant == PBA_NO_DERATE else self.f[("late", "data")]
        for prev, node in zip(path, path[1:]):
            pin = node[0]
            if (
                "/" not in pin
                or self.cell_of(pin)["pins"][pin.split("/")[1]]["direction"] == "input"
            ):
                continue
            rel = prev[0].split("/")[1]
            arc = next(a for a in self.arcs_to(pin) if a["related_pin"] == rel)
            d, slew = self.arc_eval(
                arc, node[1], slew, self.load(self.net_of[pin]), factor
            )
            arrival += d
        r = self.darr(ep)[tr][tag]
        if "/" not in ep:
            d = next(x for x in self.cons["output_delay"] if x["port"] == ep)
            nm = self.applicable(tag, {("port", ep), ("clock", d["clock"])})
            S, _PL, PC = self.relation(tag[0], tag[1], d["clock"], "rise")
            return float(S + (nm[0] - 1) * PC) - d["max"] * self.sts - arrival
        return self._seq_check(ep, tr, tag, [arrival, slew] + list(r[2:]))[0]

    def diagnostics(self, report):
        credits = []
        for ep in report["endpoints"]:
            if "/" not in ep:
                continue
            for tr in TRS:
                for tag, r in self.darr(ep)[tr].items():
                    inst = ep.split("/")[0]
                    ck = f"{inst}/{'G' if 'latch' in self.cell_of(ep) else 'CK'}"
                    if (
                        self.applicable(
                            tag,
                            {("pin", ep), ("cell", inst), ("clock", self.clock_of[ck])},
                        )
                        is not None
                    ):
                        credits.append(
                            self.credit(
                                self.launch_of(ep, tr, tag, "late"),
                                "late",
                                ck,
                                "rise",
                                "early",
                            )
                        )
        gen = {g["name"] for g in self.cons["generated"]}
        gen_latch = 0
        for ep in report["endpoints"]:
            if "/" in ep and "latch" in self.cell_of(ep):
                inst = ep.split("/")[0]
                objs = {
                    ("pin", ep),
                    ("cell", inst),
                    ("clock", self.clock_of[f"{inst}/G"]),
                }
                for tr in TRS:
                    gen_latch += sum(
                        1
                        for tag in self.darr(ep)[tr]
                        if tag[0] in gen and self.applicable(tag, objs) is not None
                    )
        return {
            "max_opp": max(self.opp, default=0.0),
            "credit_depth": max(self.cdepth, default=0),
            "extrap_vars": sorted(x for x in self.extrap_vars if x),
            "used_templates": sorted(self.used_templates),
            "gen_latch": gen_latch,
            "extrapolations": self.extrap,
            "max_credit": max(credits, default=0.0),
            "max_borrow": max(
                [b for b in report["borrow"].values() if b is not None], default=0.0
            ),
            "min_gap": min([g for g in self.gaps if g > 0], default=1.0),
            "pba_min_gap": min(self.pba_gaps, default=1.0),
            "tie_hit": bool(
                (self.ties["late"] & self.traced["late"])
                or (self.ties["early"] & self.traced["early"])
            ),
        }


def analyse(lib, netlist, cons, variant=None):
    return Ref(lib, netlist, cons, variant).analyse()


def analyse_with_diagnostics(lib, netlist, cons):
    ref = Ref(lib, netlist, cons)
    report = ref.analyse()
    return report, ref.diagnostics(report)
