# FORGE-CANARY-BEGIN
# FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-END
"""Static timing analyser: Liberty NLDM + structural Verilog + SDC -> JSON timing report.

python3 sta.py --lib L --netlist N --sdc S --out R

Graph-based analysis with propagated or ideal clocks, CPPR, generated clocks, multicycle and false
paths, level-sensitive latch time borrowing, OCV cell-delay derates, and path-based re-timing
of the worst setup endpoints. Standard library only.
"""

import argparse
import json
import math
import re
import sys
from fractions import Fraction


class Malformed(Exception):
    pass


# ============================================================================ Liberty
class Group:
    def __init__(self, kind, args):
        self.kind, self.args = kind, args
        self.attrs, self.complex, self.groups = {}, [], []

    def sub(self, kind):
        return [g for g in self.groups if g.kind == kind]


LIB_TOKEN = re.compile(
    r'\s*(?:(/\*.*?\*/)|("(?:[^"\\]|\\.)*")|([A-Za-z_][\w.!]*|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|([(){}:;,]))',
    re.S,
)


def lib_tokens(text):
    pos, out = 0, []
    text = text.replace("\\\n", " ")
    while pos < len(text):
        if not text[pos:].strip():
            break
        m = LIB_TOKEN.match(text, pos)
        if not m:
            raise Malformed(f"library: unexpected text at offset {pos}")
        pos = m.end()
        if m.group(1):
            continue
        out.append(m.group(2) or m.group(3) or m.group(4))
    return out


def parse_liberty(text):
    toks = lib_tokens(text)
    i = 0

    def expect(t):
        nonlocal i
        if i >= len(toks) or toks[i] != t:
            raise Malformed(f"library: expected {t!r} at token {i}")
        i += 1

    def args():
        nonlocal i
        expect("(")
        out = []
        while i < len(toks) and toks[i] != ")":
            if toks[i] != ",":
                out.append(toks[i].strip('"'))
            i += 1
        expect(")")
        return out

    def group(kind, a):
        nonlocal i
        g = Group(kind, a)
        expect("{")
        while i < len(toks) and toks[i] != "}":
            name = toks[i]
            i += 1
            if i >= len(toks):
                break
            if toks[i] == ":":
                i += 1
                if i >= len(toks):
                    break
                g.attrs[name] = toks[i].strip('"')
                i += 1
                expect(";")
            elif toks[i] == "(":
                a2 = args()
                if i < len(toks) and toks[i] == "{":
                    g.groups.append(group(name, a2))
                else:
                    expect(";")
                    g.complex.append((name, a2))
            else:
                raise Malformed(f"library: malformed statement at {name!r}")
        expect("}")
        return g

    if not toks or toks[0] != "library":
        raise Malformed("library: no library group")
    i = 1
    top = group("library", args())
    if i != len(toks):
        raise Malformed("library: text after the library group")
    return top


def floats(s):
    try:
        return [float(x) for x in s.replace(",", " ").split()]
    except ValueError as e:
        raise Malformed(f"library: bad number list {s!r}") from e


class Library:
    TIME = {"1ps": 1e-3, "1ns": 1.0}
    CAP = {"ff": 1e-3, "pf": 1.0}

    def __init__(self, text):
        g = parse_liberty(text)
        try:
            self.tunit = self.TIME[g.attrs["time_unit"]]
            cu = [c for c in g.complex if c[0] == "capacitive_load_unit"][0][1]
            self.cunit = float(cu[0]) * self.CAP[cu[1].lower()]
        except (KeyError, IndexError, ValueError) as e:
            raise Malformed("library: units missing or unknown") from e
        self.templates = {}
        for t in g.sub("lu_table_template"):
            vars_ = [
                t.attrs[f"variable_{k}"] for k in (1, 2) if f"variable_{k}" in t.attrs
            ]
            idx = []
            for k in range(1, len(vars_) + 1):
                c = [x for x in t.complex if x[0] == f"index_{k}"]
                if not c:
                    raise Malformed(f"library: template {t.args[0]} lacks index_{k}")
                scale = (
                    self.cunit
                    if vars_[k - 1] == "total_output_net_capacitance"
                    else self.tunit
                )
                idx.append([x * scale for x in floats(",".join(c[0][1]))])
            self.templates[t.args[0]] = (vars_, idx)
        wl = {w.args[0]: w for w in g.sub("wire_load")}
        name = g.attrs.get("default_wire_load")
        if name not in wl:
            raise Malformed("library: default_wire_load names no wire_load")
        w = wl[name]
        try:
            self.wire_c = float(w.attrs["capacitance"]) * self.cunit
            self.wire_slope = float(w.attrs["slope"])
            self.fanout_len = sorted(
                (int(float(a[0])), float(a[1]))
                for k, a in w.complex
                if k == "fanout_length"
            )
        except (KeyError, ValueError, IndexError) as e:
            raise Malformed("library: incomplete wire_load") from e
        if not self.fanout_len:
            raise Malformed("library: wire_load without fanout_length")
        self.cells = {c.args[0]: self._cell(c) for c in g.sub("cell")}

    def _table(self, grp):
        if not grp.args or grp.args[0] not in self.templates:
            raise Malformed(f"library: table {grp.kind} names an unknown template")
        vars_, idx = self.templates[grp.args[0]]
        vals = [c for c in grp.complex if c[0] == "values"]
        if not vals:
            raise Malformed("library: table without values")
        rows = [[x * self.tunit for x in floats(r)] for r in vals[0][1]]
        if len(vars_) == 1:
            flat = [x for r in rows for x in r]
            if len(flat) != len(idx[0]):
                raise Malformed("library: table size differs from its template")
            return (vars_, idx, flat)
        if len(rows) != len(idx[0]) or any(len(r) != len(idx[1]) for r in rows):
            raise Malformed("library: table size differs from its template")
        return (vars_, idx, rows)

    def _cell(self, c):
        cell = {"pins": {}, "arcs": [], "checks": {}, "seq": None}
        if c.sub("ff"):
            cell["seq"] = ("ff", c.sub("ff")[0].attrs.get("clocked_on", "").strip())
        if c.sub("latch"):
            cell["seq"] = ("latch", c.sub("latch")[0].attrs.get("enable", "").strip())
        for p in c.sub("pin"):
            name = p.args[0]
            d = p.attrs.get("direction")
            if d not in ("input", "output"):
                raise Malformed(f"library: pin {name} lacks a direction")
            cell["pins"][name] = {
                "dir": d,
                "cap": float(p.attrs.get("capacitance", 0)) * self.cunit,
                "clock": p.attrs.get("clock") == "true",
            }
            for t in p.sub("timing"):
                rel = t.attrs.get("related_pin")
                ttype = t.attrs.get("timing_type", "combinational")
                tables = {s.kind: self._table(s) for s in t.groups}
                if ttype in ("combinational", "rising_edge"):
                    cell["arcs"].append(
                        {
                            "from": rel,
                            "to": name,
                            "type": ttype,
                            "sense": t.attrs.get("timing_sense", "positive_unate"),
                            "t": tables,
                        }
                    )
                elif ttype in (
                    "setup_rising",
                    "hold_rising",
                    "setup_falling",
                    "hold_falling",
                ):
                    cell["checks"][ttype.split("_")[0]] = tables
                else:
                    raise Malformed(f"library: unsupported timing_type {ttype}")
        return cell

    def lookup(self, table, values):
        vars_, idx, data = table
        try:
            xs = [values[v] for v in vars_]
        except KeyError as e:
            raise Malformed(f"library: unsupported table variable {e}") from e
        if len(vars_) == 1:
            return interp(idx[0], data, xs[0])
        return interp(idx[0], [interp(idx[1], r, xs[1]) for r in data], xs[0])

    def wire(self, fanout):
        if fanout <= 0:
            return 0.0
        pts = self.fanout_len
        for f, length in pts:
            if f == fanout:
                return length * self.wire_c
        if fanout > pts[-1][0]:
            return (pts[-1][1] + self.wire_slope * (fanout - pts[-1][0])) * self.wire_c
        lo = max(p for p in pts if p[0] < fanout)
        hi = min(p for p in pts if p[0] > fanout)
        return (
            lo[1] + (hi[1] - lo[1]) * (fanout - lo[0]) / (hi[0] - lo[0])
        ) * self.wire_c


def interp(index, values, x):
    n = len(index)
    if n == 1:
        return values[0]
    k = 0
    while k < n - 2 and x >= index[k + 1]:
        k += 1
    return values[k] + (values[k + 1] - values[k]) * (x - index[k]) / (
        index[k + 1] - index[k]
    )


# ============================================================================ Verilog
def parse_verilog(text, lib):
    text = re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S)
    m = re.search(r"\bmodule\s+(\w+)\s*\(([^)]*)\)\s*;(.*)\bendmodule\b", text, re.S)
    if not m:
        raise Malformed("netlist: no module")
    inputs, outputs, insts, assigns = [], [], [], {}
    for stmt in m.group(3).split(";"):
        s = stmt.strip()
        if not s:
            continue
        if s.startswith(("input ", "output ", "wire ")):
            kind, rest = s.split(None, 1)
            names = [x.strip() for x in rest.split(",") if x.strip()]
            if kind == "input":
                inputs += names
            elif kind == "output":
                outputs += names
            continue
        a = re.fullmatch(r"assign\s+(\w+)\s*=\s*(\w+)", s)
        if a:
            assigns[a.group(1)] = a.group(2)
            continue
        im = re.fullmatch(r"(\w+)\s+(\w+)\s*\((.*)\)", s, re.S)
        if not im:
            raise Malformed(f"netlist: cannot read statement {s[:40]!r}")
        cell, name, conns_txt = im.groups()
        if cell not in lib.cells:
            raise Malformed(f"netlist: instance {name} uses undefined cell {cell}")
        conns = {}
        for pm in re.finditer(r"\.(\w+)\s*\(\s*(\w*)\s*\)", conns_txt):
            if pm.group(1) not in lib.cells[cell]["pins"]:
                raise Malformed(f"netlist: {name} connects undefined pin {pm.group(1)}")
            conns[pm.group(1)] = pm.group(2)
        insts.append({"name": name, "cell": cell, "conns": conns})
    for port in outputs:
        if port not in assigns:
            raise Malformed(f"netlist: output {port} is not assigned")
    return {"inputs": inputs, "outputs": outputs, "insts": insts, "assigns": assigns}


# ============================================================================ SDC
def sdc_words(line):
    out, i = [], 0
    while i < len(line):
        ch = line[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "[{":
            close = "]" if ch == "[" else "}"
            depth, j = 0, i
            while j < len(line):
                if line[j] == ch:
                    depth += 1
                elif line[j] == close:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(line):
                raise Malformed("constraints: unbalanced bracket")
            out.append(line[i : j + 1])
            i = j + 1
        else:
            j = i
            while j < len(line) and not line[j].isspace():
                j += 1
            out.append(line[i:j])
            i = j
    return out


class Constraints:
    UNITS = {"ns": Fraction(1), "ps": Fraction(1, 1000)}
    CAPS = {"pf": 1.0, "ff": 1e-3}

    def __init__(self, text, design, lib):
        self.d = design
        self.tu, self.cu = Fraction(1), 1.0
        self.clocks, self.generated = {}, {}
        self.propagated = set()
        self.clock_tr, self.in_tr, self.load = {}, {}, {}
        self.in_delay, self.out_delay = {}, {}
        self.exceptions, self.derate = [], {}
        self.pins = {
            f"{i['name']}/{p}"
            for i in design["insts"]
            for p in lib.cells[i["cell"]]["pins"]
        }
        self.cells = {i["name"] for i in design["insts"]}
        for raw in re.sub(r"\\\n", " ", text).splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                self.command(sdc_words(line))

    def num(self, w):
        try:
            return Fraction(w)
        except (ValueError, ZeroDivisionError) as e:
            raise Malformed(f"constraints: {w!r} is not a number") from e

    def objects(self, w):
        m = re.fullmatch(r"\[\s*(\w+)\s*(.*?)\s*\]", w, re.S)
        if not m:
            raise Malformed(f"constraints: cannot read object list {w!r}")
        fn, arg = m.groups()
        if fn == "all_clocks":
            return [("clock", c) for c in list(self.clocks) + list(self.generated)]
        kind = {
            "get_ports": "port",
            "get_pins": "pin",
            "get_cells": "cell",
            "get_clocks": "clock",
        }.get(fn)
        if kind is None:
            raise Malformed(f"constraints: unsupported command {fn}")
        names = arg[1:-1].split() if arg.startswith("{") else arg.split()
        known = {
            "port": set(self.d["inputs"]) | set(self.d["outputs"]),
            "pin": self.pins,
            "cell": self.cells,
            "clock": set(self.clocks) | set(self.generated),
        }[kind]
        if not names:
            raise Malformed(f"constraints: {fn} without a name")
        for n in names:
            if n not in known:
                raise Malformed(f"constraints: {fn} {n} matches nothing")
        return [(kind, n) for n in names]

    @staticmethod
    def options(words, flags, values):
        opts, pos, i = {}, [], 0
        while i < len(words):
            w = words[i]
            if w in flags:
                opts[w] = True
                i += 1
            elif w in values:
                if i + 1 >= len(words):
                    raise Malformed(f"constraints: {w} needs a value")
                opts.setdefault(w, []).append(words[i + 1])
                i += 2
            elif w.startswith("-") and not re.fullmatch(
                r"-(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", w
            ):
                raise Malformed(f"constraints: unknown option {w}")
            else:
                pos.append(w)
                i += 1
        return opts, pos

    def command(self, w):
        cmd, rest = w[0], w[1:]
        if cmd == "set_units":
            o, pos = self.options(rest, set(), {"-time", "-capacitance"})
            try:
                if "-time" in o:
                    self.tu = self.UNITS[o["-time"][0].lower()]
                if "-capacitance" in o:
                    self.cu = self.CAPS[o["-capacitance"][0].lower()]
            except KeyError as e:
                raise Malformed("constraints: unknown unit") from e
        elif cmd == "create_clock":
            o, pos = self.options(rest, set(), {"-name", "-period", "-waveform"})
            if "-period" not in o or len(pos) != 1:
                raise Malformed("create_clock: -period and one source are required")
            src = self.objects(pos[0])
            period = self.num(o["-period"][0]) * self.tu
            if "-waveform" in o:
                wave = [
                    self.num(x) * self.tu for x in o["-waveform"][0].strip("{}").split()
                ]
                if len(wave) != 2:
                    raise Malformed("create_clock: -waveform needs two edges")
            else:
                wave = [Fraction(0), period / 2]
            name = o.get("-name", [src[0][1]])[0]
            self.clocks[name] = {
                "P": period,
                "rise": wave[0],
                "fall": wave[1],
                "root": src[0][1],
            }
        elif cmd == "create_generated_clock":
            o, pos = self.options(
                rest,
                set(),
                {
                    "-name",
                    "-source",
                    "-divide_by",
                    "-multiply_by",
                    "-edges",
                    "-master_clock",
                },
            )
            if (
                "-source" not in o
                or len(pos) != 1
                or not ({"-divide_by", "-multiply_by", "-edges"} & set(o))
            ):
                raise Malformed(
                    "create_generated_clock: -source, a derivation, and one target are required"
                )
            target = self.objects(pos[0])[0][1]
            g = {"pin": target, "source": self.objects(o["-source"][0])[0][1]}
            if "-divide_by" in o:
                k = int(o["-divide_by"][0])
                g["edges"] = [1, k + 1, 2 * k + 1]
            elif "-multiply_by" in o:
                g["multiply"] = int(o["-multiply_by"][0])
            else:
                g["edges"] = [int(x) for x in o["-edges"][0].strip("{}").split()]
                if len(g["edges"]) != 3:
                    raise Malformed("create_generated_clock: -edges needs three edges")
            self.generated[o.get("-name", [target])[0]] = g
        elif cmd == "set_propagated_clock":
            for _, n in self.objects(rest[0]):
                self.propagated.add(n)
        elif cmd in ("set_clock_transition", "set_input_transition", "set_load"):
            if len(rest) != 2:
                raise Malformed(f"{cmd}: a value and objects are required")
            for _, n in self.objects(rest[1]):
                if cmd == "set_load":
                    self.load[n] = float(self.num(rest[0])) * self.cu
                else:
                    (self.clock_tr if cmd == "set_clock_transition" else self.in_tr)[
                        n
                    ] = float(self.num(rest[0]) * self.tu)
        elif cmd in ("set_input_delay", "set_output_delay"):
            o, pos = self.options(rest, {"-max", "-min"}, {"-clock"})
            if "-clock" not in o or len(pos) != 2:
                raise Malformed(f"{cmd}: -clock, a value, and ports are required")
            clk = o["-clock"][0]
            if clk not in self.clocks and clk not in self.generated:
                raise Malformed(f"{cmd}: unknown clock {clk}")
            v = float(self.num(pos[0]) * self.tu)
            store = self.in_delay if cmd == "set_input_delay" else self.out_delay
            for _, port in self.objects(pos[1]):
                e = store.setdefault(port, {"clock": clk})
                if not o.get("-min"):
                    e["max"] = v
                if not o.get("-max"):
                    e["min"] = v
        elif cmd in ("set_false_path", "set_multicycle_path"):
            o, pos = self.options(
                rest,
                {"-setup", "-hold", "-start", "-end"},
                {"-from", "-through", "-to"},
            )
            if cmd == "set_false_path":
                if pos:
                    raise Malformed("set_false_path: stray argument")
                kind, n = "false", 0
            else:
                if len(pos) != 1:
                    raise Malformed("set_multicycle_path: one multiplier is required")
                n = int(self.num(pos[0]))
                kind = "hold" if o.get("-hold") else "setup"
            e = {"kind": kind, "n": n, "from": set(), "through": [], "to": set()}
            for w2 in o.get("-from", []):
                e["from"] |= set(self.objects(w2))
            for w2 in o.get("-through", []):
                e["through"].append({x[1] for x in self.objects(w2)})
            for w2 in o.get("-to", []):
                e["to"] |= set(self.objects(w2))
            self.exceptions.append(e)
        elif cmd == "set_timing_derate":
            o, pos = self.options(
                rest, {"-early", "-late", "-clock", "-data", "-cell_delay"}, set()
            )
            if len(pos) != 1:
                raise Malformed("set_timing_derate: one factor is required")
            f = float(self.num(pos[0]))
            for which in [x for x in ("early", "late") if o.get(f"-{x}")] or [
                "early",
                "late",
            ]:
                for where in [x for x in ("clock", "data") if o.get(f"-{x}")] or [
                    "clock",
                    "data",
                ]:
                    self.derate[(which, where)] = f
        else:
            raise Malformed(f"constraints: unsupported command {cmd}")


# ============================================================================ analysis
RISE, FALL = "rise", "fall"
PBA_ENDPOINTS = 5
FLIP = {RISE: FALL, FALL: RISE}


def lcm_frac(a, b):
    p, q = a.numerator * b.denominator, b.numerator * a.denominator
    return Fraction(p * q // math.gcd(p, q), a.denominator * b.denominator)


def input_trs(sense, tr):
    if sense == "positive_unate":
        return [tr]
    if sense == "negative_unate":
        return [FLIP[tr]]
    return [RISE, FALL]


class Analyzer:
    def __init__(self, lib, d, c):
        self.lib, self.d, self.c = lib, d, c
        self.cellof = {i["name"]: lib.cells[i["cell"]] for i in d["insts"]}
        self.drv, self.loads_on, self.net = {}, {}, {}
        for p in d["inputs"]:
            self.drv[p], self.net[p] = p, p
        for i in d["insts"]:
            for pin, n in i["conns"].items():
                full = f"{i['name']}/{pin}"
                self.net[full] = n
                if self.cellof[i["name"]]["pins"][pin]["dir"] == "output":
                    if n in self.drv:
                        raise Malformed(f"netlist: net {n} has two drivers")
                    self.drv[n] = full
                else:
                    self.loads_on.setdefault(n, []).append(full)
        for port, n in d["assigns"].items():
            self.loads_on.setdefault(n, []).append(port)
            self.net[port] = n
        for n in self.loads_on:
            if n not in self.drv:
                raise Malformed(f"netlist: net {n} has no driver")
        self.fac = {
            (a, b): c.derate.get((a, b), 1.0)
            for a in ("early", "late")
            for b in ("clock", "data")
        }
        self.capload = {}
        for n, sinks in self.loads_on.items():
            cap = 0.0
            for s in sinks:
                if "/" in s:
                    inst, p = s.split("/")
                    cap += self.cellof[inst]["pins"][p]["cap"]
                else:
                    cap += c.load.get(s, 0.0)
            self.capload[n] = cap + lib.wire(len(sinks))

    def pdir(self, pin):
        inst, p = pin.split("/")
        return self.cellof[inst]["pins"][p]

    def arcs_into(self, pin):
        inst, p = pin.split("/")
        return [a for a in self.cellof[inst]["arcs"] if a["to"] == p]

    def delay(self, arc, tr, slew, load, factor):
        v = {"input_net_transition": slew, "total_output_net_capacitance": load}
        return self.lib.lookup(arc["t"][f"cell_{tr}"], v) * factor, self.lib.lookup(
            arc["t"][f"{tr}_transition"], v
        )

    # ------------------------------------------------------------------ clock network
    def build_clocks(self):
        c = self.c
        self.waves = {
            n: {k: v[k] for k in ("P", "rise", "fall")} for n, v in c.clocks.items()
        }
        self.cnet = {}
        roots = [(v["root"], n) for n, v in c.clocks.items()]
        pending = dict(c.generated)
        while roots:
            root, clk = roots.pop(0)
            todo = [root]
            self.cnet[root] = clk
            while todo:
                pin = todo.pop()
                for s in self.loads_on.get(self.net[pin], []):
                    if "/" not in s:
                        continue
                    self.cnet[s] = clk
                    if self.pdir(s)["clock"]:
                        continue
                    inst, p = s.split("/")
                    for a in self.cellof[inst]["arcs"]:
                        if a["from"] == p and a["type"] == "combinational":
                            out = f"{inst}/{a['to']}"
                            self.cnet[out] = clk
                            todo.append(out)
            for gname, g in list(pending.items()):
                if g["source"] in self.cnet:
                    m = self.waves[self.cnet[g["source"]]]
                    if "multiply" in g:
                        k = g["multiply"]
                        self.waves[gname] = {
                            "P": m["P"] / k,
                            "rise": m["rise"],
                            "fall": m["rise"] + (m["fall"] - m["rise"]) / k,
                        }
                    else:

                        def edge(e, m=m):
                            return (m["rise"] if e % 2 else m["fall"]) + (
                                (e - 1) // 2
                            ) * m["P"]

                        e1, e2, e3 = g["edges"]
                        self.waves[gname] = {
                            "P": edge(e3) - edge(e1),
                            "rise": edge(e1),
                            "fall": edge(e2),
                        }
                    roots.append((g["pin"], gname))
                    del pending[gname]
        if pending:
            raise Malformed(
                "constraints: a generated clock's source is not on a clock network"
            )
        self.gen_at = {g["pin"]: g["source"] for g in c.generated.values()}
        self.clock_roots = {v["root"] for v in c.clocks.values()}
        self.ck = {}
        for pin in list(self.cnet):
            for tr in (RISE, FALL):
                self.clock_arrival(pin, tr)

    def clock_arrival(self, pin, tr):
        key = (pin, tr)
        if key in self.ck:
            return self.ck[key]
        if pin in self.clock_roots:
            s = self.c.in_tr.get(pin, 0.0)
            out = {"src": tr, "late": (0.0, s, None), "early": (0.0, s, None)}
        elif pin in self.gen_at:
            src = self.gen_at[pin]
            arc = [a for a in self.arcs_into(pin) if a["type"] == "rising_edge"][0]
            base = self.clock_arrival(src, RISE)
            out = {"src": tr}
            for m in ("late", "early"):
                dl, sl = self.delay(
                    arc,
                    tr,
                    base[m][1],
                    self.capload.get(self.net[pin], 0.0),
                    self.fac[(m, "clock")],
                )
                out[m] = (base[m][0] + dl, sl, (src, RISE))
        elif self.pdir(pin)["dir"] == "input":
            up = self.drv[self.net[pin]]
            b = self.clock_arrival(up, tr)
            out = {
                "src": b["src"],
                "late": (b["late"][0], b["late"][1], (up, tr)),
                "early": (b["early"][0], b["early"][1], (up, tr)),
            }
        else:
            inst = pin.split("/")[0]
            load = self.capload.get(self.net[pin], 0.0)
            cands = {"late": [], "early": []}
            src_edge = None
            for a in self.arcs_into(pin):
                if a["type"] != "combinational":
                    continue
                src_pin = f"{inst}/{a['from']}"
                for itr in input_trs(a["sense"], tr):
                    b = self.clock_arrival(src_pin, itr)
                    src_edge = src_edge or b["src"]
                    for m in ("late", "early"):
                        dl, sl = self.delay(
                            a, tr, b[m][1], load, self.fac[(m, "clock")]
                        )
                        cands[m].append((b[m][0] + dl, sl, (src_pin, itr)))
            out = {"src": src_edge}
            for m, pick in (("late", max), ("early", min)):
                best = pick(x[0] for x in cands[m])
                pred = min(x[2] for x in cands[m] if x[0] == best)
                out[m] = (best, pick(x[1] for x in cands[m]), pred)
        self.ck[key] = out
        return out

    def clock_at(self, pin, tr):
        clk = self.cnet.get(pin)
        if clk is None:
            raise Malformed(f"constraints: sequential clock pin {pin} has no clock")
        rec = self.ck[(pin, tr)]
        if clk in self.c.propagated:
            return (
                clk,
                rec["src"],
                {m: rec[m][0] for m in ("late", "early")},
                {m: rec[m][1] for m in ("late", "early")},
            )
        s = self.c.clock_tr.get(clk, 0.0)
        return clk, rec["src"], {"late": 0.0, "early": 0.0}, {"late": s, "early": s}

    def clock_path(self, pin, tr, mode):
        path, node = [], (pin, tr)
        while node is not None:
            path.append(node)
            node = self.ck[node][mode][2]
        path.reverse()
        return path

    def setup_relation(self, lclk, ledge, cclk, cedge):
        L, C = self.waves[lclk], self.waves[cclk]
        best = None
        for k in range(int(lcm_frac(L["P"], C["P"]) / L["P"])):
            launch = L[ledge] + k * L["P"]
            gap = (
                C[cedge]
                + (math.floor((launch - C[cedge]) / C["P"]) + 1) * C["P"]
                - launch
            )
            best = gap if best is None or gap < best else best
        return best, L["P"], C["P"]

    def cppr(self, lpin, lmode, cpin, ctr, cmode):
        if (
            lpin is None
            or self.cnet[lpin] not in self.c.propagated
            or self.cnet[cpin] not in self.c.propagated
        ):
            return 0.0
        cap = dict(self.clock_path(cpin, ctr, cmode))
        for p, t in reversed(self.clock_path(lpin, RISE, lmode)):
            if p in cap:
                if cap[p] != t:
                    return 0.0
                r = self.ck[(p, t)]
                return r["late"][0] - r["early"][0]
        return 0.0

    # ------------------------------------------------------------------ data
    def initial_state(self, objs):
        waiting, matched = [], []
        for k, e in enumerate(self.c.exceptions):
            if e["from"] and not (e["from"] & objs):
                continue
            if e["through"]:
                waiting.append((k, 0))
            else:
                matched.append(k)
        return tuple(sorted(waiting)), tuple(sorted(matched))

    def advance(self, tag, pin):
        clk, edge, waiting, matched = tag
        if not waiting:
            return tag
        w2, m2, changed = [], list(matched), False
        for k, stage in waiting:
            thr = self.c.exceptions[k]["through"]
            if pin in thr[stage]:
                changed = True
                if stage + 1 == len(thr):
                    m2.append(k)
                else:
                    w2.append((k, stage + 1))
            else:
                w2.append((k, stage))
        return tag if not changed else (clk, edge, tuple(sorted(w2)), tuple(sorted(m2)))

    def topo(self):
        nodes, succ, indeg = set(), {}, {}

        def edge(a, b):
            nodes.update((a, b))
            succ.setdefault(a, []).append(b)
            indeg[b] = indeg.get(b, 0) + 1

        for n, sinks in self.loads_on.items():
            src = self.drv[n]
            if src in self.cnet:
                continue
            for s in sinks:
                if s not in self.cnet:
                    edge(src, s)
        for i in self.d["insts"]:
            for a in self.cellof[i["name"]]["arcs"]:
                f, t = f"{i['name']}/{a['from']}", f"{i['name']}/{a['to']}"
                if t in self.cnet:
                    continue
                if f in self.cnet:
                    nodes.add(t)
                    continue
                edge(f, t)
        for p in self.d["inputs"]:
            if p not in self.cnet:
                nodes.add(p)
        ready = [n for n in nodes if indeg.get(n, 0) == 0]
        out = []
        while ready:
            n = ready.pop()
            out.append(n)
            for m in succ.get(n, []):
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(out) != len(nodes):
            raise Malformed("netlist: combinational loop")
        return out

    def run(self):
        self.build_clocks()
        A = self.A = {}
        self.checks, self.borrow_paths = {}, {}
        for pin in self.topo():
            A[pin] = {}
            if "/" not in pin:
                if pin in self.d["inputs"]:
                    if pin in self.c.in_delay:
                        e = self.c.in_delay[pin]
                        tag = (e["clock"], RISE) + self.initial_state(
                            {("port", pin), ("clock", e["clock"])}
                        )
                        s = self.c.in_tr.get(pin, 0.0)
                        for tr in (RISE, FALL):
                            A[pin][(tr, tag)] = [
                                e.get("max", 0.0),
                                s,
                                None,
                                e.get("min", 0.0),
                                s,
                                None,
                            ]
                else:
                    up = self.drv[self.net[pin]]
                    for (tr, tag), r in A.get(up, {}).items():
                        A[pin][(tr, tag)] = [
                            r[0],
                            r[1],
                            (up, tr, tag),
                            r[3],
                            r[4],
                            (up, tr, tag),
                        ]
                continue
            inst, p = pin.split("/")
            cell = self.cellof[inst]
            if cell["pins"][p]["dir"] == "input":
                up = self.drv[self.net[pin]]
                for (tr, tag), r in A.get(up, {}).items():
                    self.fold(
                        A[pin],
                        tr,
                        self.advance(tag, pin),
                        r[0],
                        r[1],
                        (up, tr, tag),
                        r[3],
                        r[4],
                        (up, tr, tag),
                    )
                if cell["seq"] and p != cell["seq"][1] and cell["checks"]:
                    self.check(pin)
                continue
            load = self.capload.get(self.net[pin], 0.0)
            if cell["seq"]:
                ckpin = f"{inst}/{cell['seq'][1]}"
                clk, src, lat, slew = self.clock_at(ckpin, RISE)
                tag = self.advance(
                    (clk, src) + self.initial_state({("cell", inst), ("clock", clk)}),
                    pin,
                )
                for a in self.arcs_into(pin):
                    if a["type"] != "rising_edge":
                        continue
                    for tr in (RISE, FALL):
                        dl, sl = self.delay(
                            a, tr, slew["late"], load, self.fac[("late", "data")]
                        )
                        de, se = self.delay(
                            a, tr, slew["early"], load, self.fac[("early", "data")]
                        )
                        self.fold(
                            A[pin],
                            tr,
                            tag,
                            lat["late"] + dl,
                            sl,
                            ("clk", ckpin),
                            lat["early"] + de,
                            se,
                            ("clk", ckpin),
                        )
                if cell["seq"][0] == "latch":
                    dpin = f"{inst}/D"
                    darc = [
                        a for a in self.arcs_into(pin) if a["type"] == "combinational"
                    ][0]
                    for tr, utag, arr, slw, shift in self.borrow_paths.get(dpin, []):
                        dl, sl = self.delay(
                            darc, tr, slw, load, self.fac[("late", "data")]
                        )
                        cur = A[pin][(tr, tag)]
                        val = arr - shift + dl
                        if val > cur[0]:
                            cur[0], cur[2] = val, ("borrow", dpin, tr, utag, shift)
                        cur[1] = max(cur[1], sl)
                continue
            for a in self.arcs_into(pin):
                src_pin = f"{inst}/{a['from']}"
                for (itr, tag), r in A.get(src_pin, {}).items():
                    for tr in (RISE, FALL):
                        if itr not in input_trs(a["sense"], tr):
                            continue
                        dl, sl = self.delay(
                            a, tr, r[1], load, self.fac[("late", "data")]
                        )
                        de, se = self.delay(
                            a, tr, r[4], load, self.fac[("early", "data")]
                        )
                        self.fold(
                            A[pin],
                            tr,
                            self.advance(tag, pin),
                            r[0] + dl,
                            sl,
                            (src_pin, itr, tag),
                            r[3] + de,
                            se,
                            (src_pin, itr, tag),
                        )
        for port in self.d["outputs"]:
            if port in self.c.out_delay:
                self.check(port)
        return self.report()

    @staticmethod
    def fold(slot, tr, tag, la, ls, lp, ea, es, ep):
        cur = slot.get((tr, tag))
        if cur is None:
            slot[(tr, tag)] = [la, ls, lp, ea, es, ep]
            return
        if la > cur[0] or (la == cur[0] and repr(lp) < repr(cur[2])):
            cur[0], cur[2] = la, lp
        if ea < cur[3] or (ea == cur[3] and repr(ep) < repr(cur[5])):
            cur[3], cur[5] = ea, ep
        cur[1] = max(cur[1], ls)
        cur[4] = min(cur[4], es)

    def exceptions_at(self, tag, objs):
        setup_n, hold_n = 1, 0
        for k in tag[3]:
            e = self.c.exceptions[k]
            if e["to"] and not (e["to"] & objs):
                continue
            if e["kind"] == "false":
                return None
            if e["kind"] == "setup":
                setup_n = max(setup_n, e["n"])
            else:
                hold_n = max(hold_n, e["n"])
        return setup_n, hold_n

    def origin(self, pin, tr, tag, late):
        k = 2 if late else 5
        node = (pin, tr, tag)
        while True:
            pred = self.A[node[0]][(node[1], node[2])][k]
            if pred is None:
                return None
            if pred[0] == "clk":
                return pred[1]
            if pred[0] == "borrow":
                return pred[1].split("/")[0] + "/G"
            node = pred

    def check(self, ep):
        rows = []
        if "/" not in ep:
            od = self.c.out_delay[ep]
            for (tr, tag), r in self.A.get(ep, {}).items():
                mc = self.exceptions_at(tag, {("port", ep), ("clock", od["clock"])})
                if mc is None:
                    continue
                S, PL, PC = self.setup_relation(tag[0], tag[1], od["clock"], RISE)
                S += (mc[0] - 1) * PC
                H = S - min(PL, PC) - mc[1] * PL
                rows.append(
                    (
                        tr,
                        tag,
                        float(S) - od.get("max", 0.0) - r[0],
                        r[3] - float(H) + od.get("min", 0.0),
                        None,
                    )
                )
            self.checks[ep] = rows
            return
        inst = ep.split("/")[0]
        cell = self.cellof[inst]
        is_latch = cell["seq"][0] == "latch"
        ckpin = f"{inst}/{cell['seq'][1]}"
        close = FALL if is_latch else RISE
        clk, so, lo, _ = self.clock_at(ckpin, RISE)
        _, sc, lc, slc = self.clock_at(ckpin, close)
        borrows = []
        for (tr, tag), r in self.A.get(ep, {}).items():
            mc = self.exceptions_at(tag, {("pin", ep), ("cell", inst), ("clock", clk)})
            if mc is None:
                continue
            S, PL, PC = self.setup_relation(tag[0], tag[1], clk, so)
            S += (mc[0] - 1) * PC
            credit_s = self.cppr(
                self.origin(ep, tr, tag, True), "late", ckpin, RISE, "early"
            )
            credit_h = self.cppr(
                self.origin(ep, tr, tag, False), "early", ckpin, close, "late"
            )
            su = self.lib.lookup(
                cell["checks"]["setup"][f"{tr}_constraint"],
                {
                    "constrained_pin_transition": r[1],
                    "related_pin_transition": slc["early"],
                },
            )
            ho = self.lib.lookup(
                cell["checks"]["hold"][f"{tr}_constraint"],
                {
                    "constrained_pin_transition": r[4],
                    "related_pin_transition": slc["late"],
                },
            )
            if is_latch:
                W = self.waves[clk]
                width = W[sc] + (math.floor((W[so] - W[sc]) / PC) + 1) * PC - W[so]
                limit = max(0.0, float(width) + lc["early"] - lo["early"] - su)
                opening = float(S) + lo["early"] + credit_s
                b = min(max(0.0, r[0] - opening), limit)
                setup = opening + b - r[0]
                if b > 0:
                    borrows.append((tr, tag, r[0], r[1], float(S)))
                Sc, _, _ = self.setup_relation(tag[0], tag[1], clk, sc)
                H = Sc + (mc[0] - 1) * PC - min(PL, PC) - mc[1] * PL
            else:
                b = None
                setup = float(S) + lo["early"] - su + credit_s - r[0]
                H = S - min(PL, PC) - mc[1] * PL
            hold = r[3] - (float(H) + lc["late"] + ho - credit_h)
            rows.append((tr, tag, setup, hold, b))
        self.checks[ep] = rows
        self.borrow_paths[ep] = borrows

    def report(self):
        endpoints, borrow = {}, {}
        for ep in sorted(self.checks):
            rows = self.checks[ep]
            endpoints[ep] = {
                "setup": min((r[2] for r in rows), default=None),
                "hold": min((r[3] for r in rows), default=None),
            }
            if "/" in ep and self.cellof[ep.split("/")[0]]["seq"][0] == "latch":
                borrow[ep] = max((r[4] for r in rows), default=None)
        su = [v["setup"] for v in endpoints.values() if v["setup"] is not None]
        ho = [v["hold"] for v in endpoints.values() if v["hold"] is not None]
        arrivals = {}
        for pin in sorted(self.A):
            recs = self.A[pin]
            if not recs:
                continue
            row = {}
            for tr in (RISE, FALL):
                vals = [r for (t, _), r in recs.items() if t == tr]
                row[f"late_{tr}"] = max((r[0] for r in vals), default=None)
                row[f"early_{tr}"] = min((r[3] for r in vals), default=None)
            arrivals[pin] = {
                k: row[k]
                for k in ("late_rise", "late_fall", "early_rise", "early_fall")
            }
        return {
            "wns_setup": min(su) if su else None,
            "tns_setup": sum(min(0.0, s) for s in su),
            "wns_hold": min(ho) if ho else None,
            "tns_hold": sum(min(0.0, s) for s in ho),
            "endpoints": endpoints,
            "arrivals": arrivals,
            "borrow": borrow,
            "pba_setup": self.pba(endpoints),
        }

    def pba(self, endpoints):
        ranked = sorted(
            (v["setup"], ep)
            for ep, v in endpoints.items()
            if v["setup"] is not None
            and ("/" not in ep or self.cellof[ep.split("/")[0]]["seq"][0] == "ff")
        )
        out = {}
        for _slack, ep in ranked[:PBA_ENDPOINTS]:
            tr, tag = min(
                ((r[2], r[0] != RISE, repr(r[1])), (r[0], r[1])) for r in self.checks[ep]
            )[1]
            out[ep] = self.retime(ep, tr, tag)
        return out

    def retime(self, ep, tr, tag):
        path, node = [], (ep, tr, tag)
        while True:
            path.append(node)
            pred = self.A[node[0]][(node[1], node[2])][2]
            if pred is None or pred[0] in ("clk", "borrow"):
                break
            node = pred
        path.reverse()
        start = self.A[path[0][0]][(path[0][1], path[0][2])]
        arrival, slew = start[0], start[1]
        for prev, node in zip(path, path[1:]):
            pin = node[0]
            if "/" not in pin or self.pdir(pin)["dir"] == "input":
                continue
            src = prev[0].split("/")[1]
            arc = next(
                a
                for a in self.arcs_into(pin)
                if a["type"] == "combinational" and a["from"] == src
            )
            d, slew = self.delay(
                arc,
                node[1],
                slew,
                self.capload.get(self.net[pin], 0.0),
                self.fac[("late", "data")],
            )
            arrival += d
        if "/" not in ep:
            od = self.c.out_delay[ep]
            mc = self.exceptions_at(tag, {("port", ep), ("clock", od["clock"])})
            S, _PL, PC = self.setup_relation(tag[0], tag[1], od["clock"], RISE)
            return float(S + (mc[0] - 1) * PC) - od.get("max", 0.0) - arrival
        inst = ep.split("/")[0]
        cell = self.cellof[inst]
        ckpin = f"{inst}/{cell['seq'][1]}"
        clk, so, lo, slc = self.clock_at(ckpin, RISE)
        mc = self.exceptions_at(tag, {("pin", ep), ("cell", inst), ("clock", clk)})
        S, _PL, PC = self.setup_relation(tag[0], tag[1], clk, so)
        S += (mc[0] - 1) * PC
        credit = self.cppr(self.origin(ep, tr, tag, True), "late", ckpin, RISE, "early")
        su = self.lib.lookup(
            cell["checks"]["setup"][f"{tr}_constraint"],
            {"constrained_pin_transition": slew, "related_pin_transition": slc["early"]},
        )
        return float(S) + lo["early"] - su + credit - arrival

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Static timing analysis: Liberty + Verilog + SDC -> JSON report."
    )
    ap.add_argument("--lib", required=True)
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--sdc", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        with open(args.lib) as fh:
            lib = Library(fh.read())
        with open(args.netlist) as fh:
            design = parse_verilog(fh.read(), lib)
        with open(args.sdc) as fh:
            cons = Constraints(fh.read(), design, lib)
        report = Analyzer(lib, design, cons).run()
    except (Malformed, OSError, KeyError, IndexError, ValueError, TypeError) as e:
        print(f"sta: {e}", file=sys.stderr)
        return 2
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=1)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
