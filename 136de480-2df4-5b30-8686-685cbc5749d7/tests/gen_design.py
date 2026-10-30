"""Seeded Liberty libraries, structural Verilog netlists, and SDC constraints for the verifier.

Every case is a structured model (library, netlist, constraints) plus its three text renderings.
The verifier draws fresh seeds at verify time; nothing here is shipped to the agent. The worked
example under /app/design/example/ is built by example_case() from its own seed domain.
"""

import math
import random
from pathlib import Path

import sta_ref

SLEW, LOAD = "input_net_transition", "total_output_net_capacitance"
DATA, CLK = "constrained_pin_transition", "related_pin_transition"
COMB = {
    "INVX1": (["A"], "negative_unate", "!A"),
    "BUFX2": (["A"], "positive_unate", "A"),
    "NAND2X1": (["A", "B"], "negative_unate", "!(A&B)"),
    "NOR2X1": (["A", "B"], "negative_unate", "!(A|B)"),
    "AND2X1": (["A", "B"], "positive_unate", "(A&B)"),
    "XOR2X1": (["A", "B"], "non_unate", "(A^B)"),
    "AOI21X1": (["A", "B", "C"], "negative_unate", "!((A&B)|C)"),
}
CLOCK_CELLS = {
    "CLKBUFX4": ("positive_unate", "A"),
    "CLKINVX2": ("negative_unate", "!A"),
}
DATA_GATES = ["INVX1", "BUFX2", "NAND2X1", "NOR2X1", "AND2X1", "XOR2X1", "AOI21X1"]
POSITIVE_GATES = ["BUFX2", "AND2X1"]
LOAD_ONLY_CELLS = ["INVX1", "BUFX2", "NAND2X1"]
MCP_SETUP = "mcp_setup"
MCP_HOLD = "mcp_hold"
FALSE_PATH = "false_path"
STRESS = "stress"
SUMMARY = "summary"
MULTICLOCK = "multiclock"
GENERATED = "generated"
LATCH_GEN = "latch_gen_mcp"
FP_MCP = "fp_mcp"
MIXED_UNITS = "mixed_units"
THREE_ORDERS = "three_orders"
OPPOSITE = "cppr_opposite"
CPPR_DEEP = "cppr_deep"
CPPR_TIE = "cppr_tie"
LATCH_ON_GEN = "latch_on_gen"
LATCH_DERATE = "latch_derate"
GEN_OF_GEN = "gen_of_gen"
MCP_RATIO = "mcp_ratio"
LATCH_CHAIN = "latch_chain"
LATCH_GEN_DERATE = "latch_gen_derate"
PBA = "pba"
PERF = "perf"
GCLK = "gclk"
GCLK2 = "gclk2"
MASTER_SOURCE = "master"
GENERATED_SOURCE = "generated"
BAD_LIBRARY = "library-syntax"
BAD_CELL = "undefined-cell"
BAD_PIN = "undefined-pin"
BAD_OBJECT = "undefined-object"


def num(x) -> str:
    return format(x, ".10g")


# --------------------------------------------------------------------------- library


def library(
    seed,
    *,
    units=("1ps", "ff"),
    orders="mixed",
    span="normal",
    three_orders=False,
    sym_and=False,
) -> dict:
    """span: 'normal' (some extrapolation), 'wide' (operating points inside), 'narrow' (heavy extrapolation)."""
    rng = random.Random(seed)
    ts = 1.0 if units[0] == "1ps" else 1e-3  # ps -> library time unit
    cs = 1.0 if units[1] == "ff" else 1e-3  # fF -> library capacitance unit
    if span == "wide":
        slews = [0, rng.choice([1, 2, 5])] + sorted(rng.sample([3000, 5000, 8000], 2))
        loads = [0, rng.choice([0.02, 0.05])] + sorted(rng.sample([600, 900, 1500], 2))
        cslews = [0, 400, 9000]
    elif span == "narrow":
        slews = sorted(rng.sample([20, 30, 45, 60, 80, 110], 4))
        loads = sorted(rng.sample([1.5, 2.5, 4, 6, 8, 11], 4))
        cslews = sorted(rng.sample([15, 25, 40, 60], 3))
    else:
        slews = sorted(rng.sample([4, 6, 10, 18, 30, 55, 90, 140, 220, 320], 4))
        loads = sorted(rng.sample([0.4, 0.8, 1.5, 3, 5, 9, 16, 28, 45], 4))
        cslews = sorted(rng.sample([5, 10, 20, 40, 80, 160, 300], 3))
    tag = rng.randrange(100, 999)
    swap = {
        "mixed": [False, True],
        "slew_first": [False, False],
        "load_first": [True, True],
    }[orders]
    names = {
        "d0": f"dly_{tag}_{'ls' if swap[0] else 'sl'}",
        "d1": f"dly_{tag + 1}_{'ls' if swap[1] else 'sl'}",
        "c2": f"chk_{tag}_2d",
        "c1": f"chk_{tag}_1d",
        "d2": f"dly_{tag + 2}_l",
    }

    def axis(vals, scale):
        return [round(v * scale, 6) for v in vals]

    templates = {}
    for key, sw in (("d0", swap[0]), ("d1", swap[1])):
        if sw:
            templates[names[key]] = {
                "vars": [LOAD, SLEW],
                "index": [axis(loads, cs), axis(slews, ts)],
            }
        else:
            templates[names[key]] = {
                "vars": [SLEW, LOAD],
                "index": [axis(slews, ts), axis(loads, cs)],
            }
    if rng.random() < 0.5:
        templates[names["c2"]] = {
            "vars": [DATA, CLK],
            "index": [axis(slews, ts), axis(cslews, ts)],
        }
    else:
        templates[names["c2"]] = {
            "vars": [CLK, DATA],
            "index": [axis(cslews, ts), axis(slews, ts)],
        }
    templates[names["c1"]] = {"vars": [DATA], "index": [axis(slews, ts)]}

    def delay_table(tname, base, ks, kl, kq):
        t = templates[tname]
        if len(t["vars"]) == 1:
            return [
                tname,
                [
                    round((base + kl * (x / cs) + kq * math.sqrt(x / cs) * 3) * ts, 6)
                    for x in t["index"][0]
                ],
            ]
        grid = []
        for x1 in t["index"][0]:
            row = []
            for x2 in t["index"][1]:
                if t["vars"][0] == SLEW:
                    slew, load = x1 / ts, x2 / cs
                else:
                    slew, load = x2 / ts, x1 / cs
                row.append(
                    round(
                        (base + ks * slew + kl * load + kq * math.sqrt(slew * load))
                        * ts,
                        6,
                    )
                )
            grid.append(row)
        return [tname, grid]

    def check_table(tname, base, kd, kc):
        t = templates[tname]
        if len(t["vars"]) == 1:
            return [tname, [round((base + kd * x / ts) * ts, 6) for x in t["index"][0]]]
        grid = []
        for x1 in t["index"][0]:
            row = []
            for x2 in t["index"][1]:
                d, c = (x1, x2) if t["vars"][0] == DATA else (x2, x1)
                row.append(
                    round(
                        (
                            base
                            + kd * d / ts
                            + kc * c / ts
                            + 0.002 * math.sqrt(d * c) / ts
                        )
                        * ts,
                        6,
                    )
                )
            grid.append(row)
        return [tname, grid]

    def arc_tables(tname, base):
        return {
            "cell_rise": delay_table(
                tname,
                base,
                rng.uniform(0.05, 0.18),
                rng.uniform(1.8, 4.5),
                rng.uniform(0.2, 0.9),
            ),
            "cell_fall": delay_table(
                tname,
                base * 0.8,
                rng.uniform(0.04, 0.15),
                rng.uniform(1.4, 3.8),
                rng.uniform(0.2, 0.8),
            ),
            "rise_transition": delay_table(
                tname,
                3,
                rng.uniform(0.02, 0.08),
                rng.uniform(2.5, 6.0),
                rng.uniform(0.1, 0.4),
            ),
            "fall_transition": delay_table(
                tname,
                2.5,
                rng.uniform(0.02, 0.07),
                rng.uniform(2.0, 5.0),
                rng.uniform(0.1, 0.4),
            ),
        }

    dly = [names["d0"], names["d1"]]
    cells = {}
    for cell, (inputs, sense, func) in COMB.items():
        pins = {
            p: {
                "direction": "input",
                "capacitance": round(rng.uniform(0.9, 2.6) * cs, 6),
            }
            for p in inputs
        }
        timing = [
            {
                "pin": "Y",
                "related_pin": p,
                "timing_type": "combinational",
                "timing_sense": sense,
                "tables": arc_tables(rng.choice(dly), rng.uniform(6, 22)),
            }
            for p in inputs
        ]
        pins["Y"] = {"direction": "output", "function": func}
        cells[cell] = {"pins": pins, "timing": timing}
    for cell, (sense, func) in CLOCK_CELLS.items():
        cells[cell] = {
            "pins": {
                "A": {
                    "direction": "input",
                    "capacitance": round(rng.uniform(1.5, 3.0) * cs, 6),
                },
                "Y": {"direction": "output", "function": func},
            },
            "timing": [
                {
                    "pin": "Y",
                    "related_pin": "A",
                    "timing_type": "combinational",
                    "timing_sense": sense,
                    "tables": arc_tables(rng.choice(dly), rng.uniform(10, 25)),
                }
            ],
        }
    chk2, chk1 = names["c2"], names["c1"]
    cells["DFFX1"] = {
        "ff": {"clocked_on": "CK", "next_state": "D"},
        "pins": {
            "D": {
                "direction": "input",
                "capacitance": round(rng.uniform(1.0, 2.0) * cs, 6),
            },
            "CK": {
                "direction": "input",
                "capacitance": round(rng.uniform(1.0, 2.0) * cs, 6),
                "clock": True,
            },
            "Q": {"direction": "output", "function": "IQ"},
        },
        "timing": [
            {
                "pin": "Q",
                "related_pin": "CK",
                "timing_type": "rising_edge",
                "tables": arc_tables(rng.choice(dly), 36),
            },
            {
                "pin": "D",
                "related_pin": "CK",
                "timing_type": "setup_rising",
                "tables": {
                    "rise_constraint": check_table(
                        chk2, rng.uniform(18, 26), 0.09, -0.03
                    ),
                    "fall_constraint": check_table(
                        chk2, rng.uniform(22, 30), 0.11, -0.04
                    ),
                },
            },
            {
                "pin": "D",
                "related_pin": "CK",
                "timing_type": "hold_rising",
                "tables": {
                    "rise_constraint": check_table(chk1, rng.uniform(-6, 4), 0.03, 0.0),
                    "fall_constraint": check_table(
                        chk2, rng.uniform(-4, 6), 0.04, 0.02
                    ),
                },
            },
        ],
    }
    cells["DLATX1"] = {
        "latch": {"enable": "G", "data_in": "D"},
        "pins": {
            "D": {
                "direction": "input",
                "capacitance": round(rng.uniform(1.0, 2.0) * cs, 6),
            },
            "G": {
                "direction": "input",
                "capacitance": round(rng.uniform(1.0, 2.0) * cs, 6),
                "clock": True,
            },
            "Q": {"direction": "output", "function": "IQ"},
        },
        "timing": [
            {
                "pin": "Q",
                "related_pin": "G",
                "timing_type": "rising_edge",
                "tables": arc_tables(rng.choice(dly), 30),
            },
            {
                "pin": "Q",
                "related_pin": "D",
                "timing_type": "combinational",
                "timing_sense": "positive_unate",
                "tables": arc_tables(rng.choice(dly), 24),
            },
            {
                "pin": "D",
                "related_pin": "G",
                "timing_type": "setup_falling",
                "tables": {
                    "rise_constraint": check_table(
                        chk2, rng.uniform(16, 24), 0.08, -0.02
                    ),
                    "fall_constraint": check_table(chk1, rng.uniform(18, 26), 0.1, 0.0),
                },
            },
            {
                "pin": "D",
                "related_pin": "G",
                "timing_type": "hold_falling",
                "tables": {
                    "rise_constraint": check_table(
                        chk2, rng.uniform(-5, 5), 0.03, 0.01
                    ),
                    "fall_constraint": check_table(
                        chk2, rng.uniform(-5, 5), 0.02, 0.02
                    ),
                },
            },
        ],
    }
    k = rng.randint(3, 5)
    lengths, acc = [], 0.0
    for f in range(1, k + 1):
        acc += rng.uniform(0.6, 1.4)
        lengths.append([f, round(acc, 4)])
    wire = {
        "name": f"wl_{tag}",
        "capacitance": round(rng.uniform(0.25, 0.6) * cs, 6),
        "slope": round(rng.uniform(0.5, 1.2), 4),
        "fanout_length": lengths,
    }
    if sym_and:
        a_arc, b_arc = cells["AND2X1"]["timing"]
        b_arc["tables"] = {
            k: [v[0], [row[:] if isinstance(row, list) else row for row in v[1]]]
            for k, v in a_arc["tables"].items()
        }
        pins = cells["AND2X1"]["pins"]
        pins["B"]["capacitance"] = pins["A"]["capacitance"]
    if three_orders:
        templates[names["d2"]] = {"vars": [LOAD], "index": [axis(loads, cs)]}
        for cell in LOAD_ONLY_CELLS:
            for arc in cells[cell]["timing"]:
                arc["tables"] = arc_tables(names["d2"], rng.uniform(6, 22))
    return {
        "name": f"stdlib_{tag}",
        "time_unit": units[0],
        "cap_unit": units[1],
        "templates": templates,
        "wire_load": wire,
        "cells": cells,
    }


def _values(v) -> str:
    if v and isinstance(v[0], list):
        return ", ".join('"' + ", ".join(num(x) for x in row) + '"' for row in v)
    return '"' + ", ".join(num(x) for x in v) + '"'


def library_text(lib: dict) -> str:
    out = [
        f"library ({lib['name']}) {{",
        "  delay_model : table_lookup ;",
        f'  time_unit : "{lib["time_unit"]}" ;',
        f"  capacitive_load_unit (1, {lib['cap_unit']}) ;",
        f'  default_wire_load : "{lib["wire_load"]["name"]}" ;',
    ]
    for name, t in lib["templates"].items():
        out.append(f"  lu_table_template ({name}) {{")
        for k, var in enumerate(t["vars"], 1):
            out.append(f"    variable_{k} : {var} ;")
        for k, idx in enumerate(t["index"], 1):
            out.append(f'    index_{k} ("{", ".join(num(x) for x in idx)}") ;')
        out.append("  }")
    w = lib["wire_load"]
    out.append(f'  wire_load ("{w["name"]}") {{')
    out.append(f"    capacitance : {num(w['capacitance'])} ;")
    out.append(f"    slope : {num(w['slope'])} ;")
    for f, length in w["fanout_length"]:
        out.append(f"    fanout_length ({f}, {num(length)}) ;")
    out.append("  }")
    for cname, c in lib["cells"].items():
        out.append(f"  cell ({cname}) {{")
        if "ff" in c:
            out.append(
                f'    ff (IQ, IQN) {{ clocked_on : "{c["ff"]["clocked_on"]}" ; next_state : "{c["ff"]["next_state"]}" ; }}'
            )
        if "latch" in c:
            out.append(
                f'    latch (IQ, IQN) {{ enable : "{c["latch"]["enable"]}" ; data_in : "{c["latch"]["data_in"]}" ; }}'
            )
        for pname, p in c["pins"].items():
            out.append(f"    pin ({pname}) {{")
            out.append(f"      direction : {p['direction']} ;")
            if "capacitance" in p:
                out.append(f"      capacitance : {num(p['capacitance'])} ;")
            if p.get("clock"):
                out.append("      clock : true ;")
            if "function" in p:
                out.append(f'      function : "{p["function"]}" ;')
            for t in c["timing"]:
                if t["pin"] != pname:
                    continue
                out.append("      timing () {")
                out.append(f'        related_pin : "{t["related_pin"]}" ;')
                if t["timing_type"] != "combinational":
                    out.append(f"        timing_type : {t['timing_type']} ;")
                if "timing_sense" in t:
                    out.append(f"        timing_sense : {t['timing_sense']} ;")
                for kind, (tname, vals) in t["tables"].items():
                    out.append(
                        f"        {kind} ({tname}) {{ values ({_values(vals)}) ; }}"
                    )
                out.append("      }")
            out.append("    }")
        out.append("  }")
    out.append("}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- design


class _Builder:
    def __init__(self, rng):
        self.rng = rng
        self.inputs, self.outputs, self.insts, self.assigns = [], [], [], {}
        self.count = {}

    def name(self, prefix):
        n = self.count.get(prefix, 0)
        self.count[prefix] = n + 1
        return f"{prefix}{n}"

    def add(self, cell, prefix, conns):
        inst = {"name": self.name(prefix), "cell": cell, "conns": conns}
        self.insts.append(inst)
        return inst


def _clock_tree(b, root_net, sinks, *, depth, reconverge, label):
    """Buffer tree from root_net; returns one leaf net per sink."""
    rng = b.rng
    level = [root_net]
    for _ in range(depth):
        nxt = []
        for net in level:
            for _ in range(2):
                out = b.name(f"{label}n")
                b.add("CLKBUFX4", f"{label}b", {"A": net, "Y": out})
                nxt.append(out)
        level = nxt
    if reconverge and len(level) >= 2:
        a, c = rng.sample(level, 2)
        out = b.name(f"{label}n")
        b.add("AND2X1", f"{label}m", {"A": a, "B": c, "Y": out})
        out2 = b.name(f"{label}n")
        b.add("CLKBUFX4", f"{label}b", {"A": out, "Y": out2})
        level = level + [out2, out2]
    return [
        level[i % len(level)] if rng.random() < 0.8 else rng.choice(level)
        for i in range(sinks)
    ]


def design(seed, spec: dict) -> tuple[dict, dict]:
    """Returns (netlist, constraints) for a spec; constraint numbers are in the SDC's set_units."""
    rng = random.Random(seed)
    b = _Builder(rng)
    sunit = spec.get("sdc_units", ("ns", "pF"))
    tsc = 1.0 if sunit[0] == "ns" else 1000.0
    csc = 1.0 if sunit[1] == "pF" else 1000.0
    u = rng.choice([0.05, 0.1, 0.04])
    clocks, generated = [], []
    n_clocks = spec.get("clocks", 1)
    first_steps = None
    for k in range(n_clocks):
        port = "clk" if k == 0 else f"clk{k + 1}"
        b.inputs.append(port)
        if k == 0:
            steps = rng.randint(7, 14)
            first_steps = steps
        else:
            steps = rng.choice([s for s in range(5, 17) if s != first_steps])
        period = round(steps * u, 6)
        rise = (
            0.0
            if (k == 0 or not spec.get("offset_waveform"))
            else round(rng.randint(1, steps - 2) * u / 2, 6)
        )
        fall = round(rise + rng.randint(2, 2 * steps - 2) * u / 4, 6)
        if fall >= rise + period:
            fall = round(rise + period / 2, 6)
        clocks.append(
            {"name": port, "port": port, "period": period, "waveform": [rise, fall]}
        )
    master = clocks[0]["name"]
    n_in = spec.get("inputs", 4)
    for i in range(n_in):
        b.inputs.append(f"in{i}")
    signals = {
        c["name"]: [f"in{i}" for i in range(n_in) if i % n_clocks == ci]
        for ci, c in enumerate(clocks)
    }
    domain_of = {f"in{i}": clocks[i % n_clocks]["name"] for i in range(n_in)}
    origins = {f"in{i}": {clocks[i % n_clocks]["name"]} for i in range(n_in)}
    flops_per = spec.get("flops", 6)
    latches = spec.get("latches", 0)
    gen = spec.get("generated")
    leaves = {}
    for ci, c in enumerate(clocks):
        count = flops_per + (latches if ci == 0 else 0) + (1 if gen and ci == 0 else 0)
        leaves[c["name"]] = _clock_tree(
            b,
            c["port"],
            count,
            depth=spec.get("tree_depth", 2),
            reconverge=spec.get("reconverge", False) and ci == 0,
            label=f"c{ci}b",
        )
    flop_specs = [
        (c["name"], leaves[c["name"]][i]) for c in clocks for i in range(flops_per)
    ]
    for _ in range(spec.get("inverted", 0)):
        shared = [
            i
            for i, (d, ck) in enumerate(flop_specs)
            if d == master and sum(1 for d2, ck2 in flop_specs if ck2 == ck) >= 2
        ]
        if not shared:
            break
        i = rng.choice(shared)
        inv = b.name("kn")
        b.add("CLKINVX2", "ki", {"A": flop_specs[i][1], "Y": inv})
        flop_specs[i] = (master, inv)
    gclk = None
    if gen:
        kind, val = gen
        b.inputs.append("en")
        signals[master].append("en")
        domain_of["en"] = master
        origins["en"] = {master}
        div = b.add("DFFX1", "udiv", {"D": "en", "CK": leaves[master][-1], "Q": "gq"})
        gclk = GCLK
        generated.append(
            {
                "name": gclk,
                "source_pin": f"{div['name']}/CK",
                "pin": f"{div['name']}/Q",
                kind: val,
            }
        )
        second = spec.get("generated2")
        gen_leaves = _clock_tree(
            b,
            "gq",
            spec.get("gen_flops", 3) + (1 if second else 0),
            depth=1,
            reconverge=False,
            label="gb",
        )
        if second:
            div2 = b.add(
                "DFFX1", "udiv", {"D": "en", "CK": gen_leaves.pop(), "Q": "gq2"}
            )
            kind2, val2 = second
            generated.append(
                {
                    "name": GCLK2,
                    "source_pin": f"{div2['name']}/CK",
                    "pin": f"{div2['name']}/Q",
                    kind2: val2,
                }
            )
            for net in _clock_tree(
                b,
                "gq2",
                spec.get("gen2_flops", 3),
                depth=1,
                reconverge=False,
                label="gc",
            ):
                flop_specs.append((GCLK2, net))
            signals[GCLK2] = []
        for net in gen_leaves:
            flop_specs.append((gclk, net))
        signals[gclk] = []
    latch_specs = []
    on_gen = spec.get("latch_enable") == GENERATED_SOURCE and gclk is not None
    for _ in range(latches):
        gnet = b.name("gn")
        b.add("CLKINVX2", "gi", {"A": "gq" if on_gen else clocks[0]["port"], "Y": gnet})
        latch_specs.append((gclk if on_gen else master, gnet))
    flops = []
    for dom, ck in flop_specs:
        q = b.name("q")
        flops.append(
            (
                {
                    "name": b.name("r"),
                    "cell": "DFFX1",
                    "conns": {"D": None, "CK": ck, "Q": q},
                },
                dom,
            )
        )
        signals.setdefault(dom, []).append(q)
        domain_of[q] = dom
        origins[q] = {dom}
    gates = spec.get("gates", 30)
    cross = spec.get("cross", 0.0)
    doms = list(signals)
    gate_set = spec.get("gate_set", DATA_GATES)

    def gate_block(count):
        made = []
        for _ in range(count):
            dom = rng.choice([d for d in doms if signals[d]])
            mine = signals[dom]
            others = [s for d in doms if d != dom for s in signals[d]]
            cell = rng.choice(gate_set)
            conns = {}
            for p in COMB[cell][0]:
                pool = mine[-10:] if rng.random() < 0.75 else mine
                if others and rng.random() < cross:
                    pool = others
                conns[p] = rng.choice(pool)
            out = b.name("n")
            conns["Y"] = out
            b.insts.append({"name": b.name("u"), "cell": cell, "conns": conns})
            signals[dom].append(out)
            domain_of[out] = dom
            origins[out] = set().union(*(origins[conns[p]] for p in COMB[cell][0]))
            made.append(out)
        return made

    first = gate_block(gates // 2)
    latch_insts = []
    source = spec.get("latch_source", MASTER_SOURCE)
    for dom, gnet in latch_specs:
        if source == GENERATED_SOURCE:
            cand = [n for n in first if gclk in origins[n]]
        else:
            cand = [n for n in first if origins[n] == {master}]
        cand = cand or first
        q = b.name("lq")
        latch_insts.append(
            {
                "name": b.name("l"),
                "cell": "DLATX1",
                "conns": {"D": rng.choice(cand[len(cand) // 2 :]), "G": gnet, "Q": q},
            }
        )
        signals[dom].append(q)
        domain_of[q] = dom
        origins[q] = {dom}
    second = gate_block(gates - gates // 2)
    for inst, (dom, _gnet) in zip(latch_insts, latch_specs):
        q = inst["conns"]["Q"]
        for _ in range(2):
            cell = rng.choice(POSITIVE_GATES + ["NAND2X1"])
            conns = {
                p: (q if k == 0 else rng.choice(signals[dom][-12:]))
                for k, p in enumerate(COMB[cell][0])
            }
            out = b.name("n")
            conns["Y"] = out
            b.insts.append({"name": b.name("u"), "cell": cell, "conns": conns})
            signals[dom].append(out)
            domain_of[out] = dom
            origins[out] = set().union(*(origins[conns[p]] for p in COMB[cell][0]))
            second.append(out)
    late = first[len(first) // 2 :] + second
    for inst, dom in flops:
        own = [n for n in late if domain_of[n] == dom] or late
        inst["conns"]["D"] = rng.choice(late if rng.random() < cross else own)
        b.insts.append(inst)
    b.insts.extend(latch_insts)
    for i, net in enumerate(rng.sample(late, min(spec.get("outputs", 3), len(late)))):
        port = f"out{i}"
        b.outputs.append(port)
        b.assigns[port] = net
    netlist = {
        "name": "top",
        "inputs": b.inputs,
        "outputs": b.outputs,
        "insts": b.insts,
        "assigns": b.assigns,
        "_flops": [i["name"] for i, _ in flops],
        "_latches": [i["name"] for i in latch_insts],
        "_gen_flops": [i["name"] for i, d in flops if d == gclk],
    }

    def t(x):
        return round(x * tsc, 6)

    period = {c["name"]: c["period"] for c in clocks}
    cons = {
        "units": {"time": sunit[0], "cap": sunit[1]},
        "clocks": [],
        "generated": generated,
        "propagated": "all" if spec.get("propagated") else None,
        "clock_transition": {},
        "input_transition": {},
        "input_delay": [],
        "output_delay": [],
        "load": {},
        "exceptions": [],
        "derates": [],
    }
    for c in clocks:
        cons["clocks"].append(
            {
                "name": c["name"],
                "port": c["port"],
                "period": t(c["period"]),
                "waveform": [t(c["waveform"][0]), t(c["waveform"][1])],
            }
        )
        cons["clock_transition"][c["name"]] = t(round(rng.uniform(0.02, 0.06), 4))
        cons["input_transition"][c["port"]] = t(round(rng.uniform(0.01, 0.05), 4))
    for p in b.inputs:
        if p in period:
            continue
        dom = domain_of.get(p, master)
        mx = round(rng.uniform(0.05, 0.35) * period[dom], 4)
        mn = round(mx * rng.uniform(0.2, 0.8), 4)
        cons["input_delay"].append(
            {
                "port": p,
                "clock": dom,
                "max": t(mx),
                "min": t(mn) if rng.random() < 0.8 else t(mx),
            }
        )
        cons["input_transition"][p] = t(round(rng.uniform(0.005, 0.12), 4))
    for port in b.outputs:
        dom = domain_of.get(b.assigns[port], master)
        if dom in (gclk, GCLK2):
            dom = master
        mx = round(rng.uniform(0.05, 0.3) * period[dom], 4)
        mn = round(rng.uniform(-0.05, 0.05) * period[dom], 4)
        cons["output_delay"].append(
            {
                "port": port,
                "clock": dom,
                "max": t(mx),
                "min": t(mn) if rng.random() < 0.8 else t(mx),
            }
        )
        cons["load"][port] = round(round(rng.uniform(0.002, 0.06), 4) * csc, 7)
    for (which, where), factor in spec.get("derates", []):
        cons["derates"].append({"which": which, "where": where, "factor": factor})
    return netlist, cons


def netlist_text(d: dict) -> str:
    nets = set()
    for inst in d["insts"]:
        nets.update(inst["conns"].values())
    nets -= set(d["inputs"])
    out = [
        f"module {d['name']} ({', '.join(d['inputs'] + d['outputs'])});",
        f"  input {', '.join(d['inputs'])};",
    ]
    if d["outputs"]:
        out.append(f"  output {', '.join(d['outputs'])};")
    if nets:
        out.append(f"  wire {', '.join(sorted(nets))};")
    for inst in d["insts"]:
        out.append(
            f"  {inst['cell']} {inst['name']} ("
            + ", ".join(f".{p}({n})" for p, n in inst["conns"].items())
            + ");"
        )
    for port in d["outputs"]:
        out.append(f"  assign {port} = {d['assigns'][port]};")
    out.append("endmodule")
    return "\n".join(out) + "\n"


def _objs(items):
    groups = {}
    for kind, name in items:
        groups.setdefault(kind, []).append(name)
    parts = []
    for kind, names in groups.items():
        fn = {
            "port": "get_ports",
            "cell": "get_cells",
            "pin": "get_pins",
            "clock": "get_clocks",
        }[kind]
        parts.append(
            f"[{fn} {{{' '.join(names)}}}]" if len(names) > 1 else f"[{fn} {names[0]}]"
        )
    return " ".join(parts)


def constraints_text(c: dict) -> str:
    out = [f"set_units -time {c['units']['time']} -capacitance {c['units']['cap']}"]
    for k in c["clocks"]:
        out.append(
            f"create_clock -name {k['name']} -period {num(k['period'])} -waveform {{{num(k['waveform'][0])} {num(k['waveform'][1])}}} [get_ports {k['port']}]"
        )
    for g in c["generated"]:
        how = (
            f"-divide_by {g['divide_by']}"
            if "divide_by" in g
            else f"-multiply_by {g['multiply_by']}"
            if "multiply_by" in g
            else f"-edges {{{' '.join(str(e) for e in g['edges'])}}}"
        )
        out.append(
            f"create_generated_clock -name {g['name']} -source [get_pins {g['source_pin']}] {how} [get_pins {g['pin']}]"
        )
    if c["propagated"] == "all":
        out.append("set_propagated_clock [all_clocks]")
    for name, v in c["clock_transition"].items():
        out.append(f"set_clock_transition {num(v)} [get_clocks {name}]")
    for port, v in c["input_transition"].items():
        out.append(f"set_input_transition {num(v)} [get_ports {port}]")
    for key, cmd in (
        ("input_delay", "set_input_delay"),
        ("output_delay", "set_output_delay"),
    ):
        for d in c[key]:
            if d["max"] == d["min"]:
                out.append(
                    f"{cmd} -clock {d['clock']} {num(d['max'])} [get_ports {d['port']}]"
                )
            else:
                out.append(
                    f"{cmd} -clock {d['clock']} -max {num(d['max'])} [get_ports {d['port']}]"
                )
                out.append(
                    f"{cmd} -clock {d['clock']} -min {num(d['min'])} [get_ports {d['port']}]"
                )
    for port, v in c["load"].items():
        out.append(f"set_load {num(v)} [get_ports {port}]")
    for e in c["exceptions"]:
        parts = [
            "set_false_path"
            if e["kind"] == "false"
            else f"set_multicycle_path {e['n']} {'-setup' if e['kind'] == MCP_SETUP else '-hold'}"
        ]
        if e.get("from"):
            parts.append("-from " + _objs(e["from"]))
        if e.get("through"):
            parts.append("-through " + _objs([("pin", p) for p in e["through"]]))
        if e.get("to"):
            parts.append("-to " + _objs(e["to"]))
        out.append(" ".join(parts))
    for d in c["derates"]:
        out.append(
            f"set_timing_derate -{d['which']} -{d['where']} -cell_delay {num(d['factor'])}"
        )
    return "\n".join(out) + "\n"


def _base_cons(clocks, rng):
    cons = {
        "units": {"time": "ns", "cap": "pF"},
        "clocks": clocks,
        "generated": [],
        "propagated": "all",
        "clock_transition": {},
        "input_transition": {},
        "input_delay": [],
        "output_delay": [],
        "load": {},
        "exceptions": [],
        "derates": [],
    }
    for c in clocks:
        cons["clock_transition"][c["name"]] = round(rng.uniform(0.02, 0.06), 4)
        cons["input_transition"][c["port"]] = round(rng.uniform(0.01, 0.05), 4)
    return cons


def _gate(b, rng, cells, first, side):
    cell = rng.choice(cells)
    conns = {}
    for k, p in enumerate(COMB[cell][0]):
        conns[p] = first if k == 0 else rng.choice(side)
    out = b.name("n")
    conns["Y"] = out
    b.insts.append({"name": b.name("u"), "cell": cell, "conns": conns})
    return out


def latch_chain_design(seed) -> tuple[dict, dict]:
    """Flops launch into a chain of alternating-phase latches, each fed through the previous latch's D-to-Q path."""
    rng = random.Random(seed)
    b = _Builder(rng)
    steps = rng.randint(6, 10)
    period = round(steps * 0.05, 6)
    fall = round(period * rng.uniform(0.4, 0.6), 4)
    b.inputs.append("clk")
    n_chain = rng.randint(3, 4)
    n_launch = rng.randint(3, 5)
    leaves = _clock_tree(
        b, "clk", n_launch + 2 + n_chain, depth=2, reconverge=False, label="c0b"
    )
    flops = []
    for i in range(n_launch + 2):
        q = b.name("q")
        flops.append(
            {
                "name": b.name("r"),
                "cell": "DFFX1",
                "conns": {"D": None, "CK": leaves[i], "Q": q},
            }
        )
    launch_q = [f["conns"]["Q"] for f in flops[:n_launch]]
    latches, prev = [], None
    for k in range(n_chain):
        gnet = b.name("gn")
        cell = "CLKINVX2" if k % 2 == 0 else "CLKBUFX4"
        b.add(cell, "gi", {"A": leaves[n_launch + 2 + k], "Y": gnet})
        net = prev if prev is not None else rng.choice(launch_q)
        for _ in range(rng.randint(4, 8)):
            net = _gate(b, rng, DATA_GATES, net, launch_q)
        q = b.name("lq")
        latches.append(
            {
                "name": b.name("l"),
                "cell": "DLATX1",
                "conns": {"D": net, "G": gnet, "Q": q},
            }
        )
        prev = q
    tails = []
    for f in flops[n_launch:]:
        net = prev
        for _ in range(rng.randint(2, 4)):
            net = _gate(b, rng, POSITIVE_GATES + ["NAND2X1"], net, launch_q)
        f["conns"]["D"] = net
        tails.append(net)
    for f in flops[:n_launch]:
        f["conns"]["D"] = _gate(
            b, rng, ["NAND2X1", "AND2X1"], rng.choice(tails), launch_q
        )
    b.insts.extend(flops)
    b.insts.extend(latches)
    netlist = {
        "name": "top",
        "inputs": b.inputs,
        "outputs": [],
        "insts": b.insts,
        "assigns": {},
        "_flops": [f["name"] for f in flops],
        "_latches": [x["name"] for x in latches],
        "_gen_flops": [],
    }
    cons = _base_cons(
        [{"name": "clk", "port": "clk", "period": period, "waveform": [0.0, fall]}], rng
    )
    cons["derates"] = [
        {"which": w, "where": "clock", "factor": f} for (w, _), f in _clock_derates(rng)
    ]
    return netlist, cons


PERF_PINS = 20000
PERF_CLOCKS = 8
PERF_EXCEPTIONS = 48
PERF_GENERATED = [
    ("g0", "clk0", "divide_by", 2),
    ("g1", "clk1", "edges", [1, 3, 7]),
    ("g2", "clk2", "multiply_by", 2),
    ("g3", "g0", "divide_by", 2),
]


def perf_design(seed) -> tuple[dict, dict]:
    """Many small register-to-register blocks over eight primary and four generated clocks.

    Every register sits in a distinct combination of exception -from lists, so each launches its own
    group, while each group's fan-out cone stays inside its block.
    """
    rng = random.Random(seed)
    b = _Builder(rng)
    clocks = []
    for k, st in enumerate(rng.sample(range(7, 21), PERF_CLOCKS)):
        period = round(st * 0.05, 6)
        clocks.append(
            {
                "name": f"clk{k}",
                "port": f"clk{k}",
                "period": period,
                "waveform": [0.0, round(rng.randint(2, 2 * st - 2) * 0.0125, 6)],
            }
        )
        b.inputs.append(f"clk{k}")
    names = [c["name"] for c in clocks] + [g[0] for g in PERF_GENERATED]
    blocks, pins = [], 0
    while pins < PERF_PINS + 600:
        lc = rng.choice(names)
        cc = lc if rng.random() < 0.75 else rng.choice(names)
        gates = [rng.choice(DATA_GATES) for _ in range(rng.randint(10, 14))]
        blocks.append((lc, cc, gates))
        pins += 15 + sum(len(COMB[g][0]) + 1 for g in gates)
    sinks = {n: 0 for n in names}
    for lc, cc, _g in blocks:
        sinks[lc] += 3
        sinks[cc] += 2
    for g, master, _k, _v in PERF_GENERATED:
        sinks[master] += 1
    leaves = {}
    for c in clocks:
        leaves[c["name"]] = _clock_tree(
            b,
            c["port"],
            sinks[c["name"]],
            depth=4,
            reconverge=False,
            label=f"{c['name']}b",
        )
    cons = _base_cons(clocks, rng)
    for g, master, kind, val in PERF_GENERATED:
        en = f"en_{g}"
        b.inputs.append(en)
        div = b.add(
            "DFFX1", "udiv", {"D": en, "CK": leaves[master].pop(), "Q": f"{g}q"}
        )
        cons["generated"].append(
            {
                "name": g,
                "source_pin": f"{div['name']}/CK",
                "pin": f"{div['name']}/Q",
                kind: val,
            }
        )
        delay = round(rng.uniform(0.02, 0.08), 4)
        cons["input_delay"].append(
            {"port": en, "clock": master, "max": delay, "min": delay}
        )
        cons["input_transition"][en] = round(rng.uniform(0.01, 0.05), 4)
        leaves[g] = _clock_tree(
            b, f"{g}q", sinks[g], depth=3, reconverge=False, label=f"{g}b"
        )
    regs, carry, through, spare = [], [], [], []
    for lc, cc, gates in blocks:
        pool = []
        for _ in range(3):
            q = b.name("q")
            regs.append(
                {
                    "name": b.name("r"),
                    "cell": "DFFX1",
                    "conns": {"D": None, "CK": leaves[lc].pop(), "Q": q},
                }
            )
            pool.append(q)
        pool += carry
        outs = []
        for cell in gates:
            conns = {p: rng.choice(pool[-6:]) for p in COMB[cell][0]}
            inst = b.name("u")
            out = b.name("n")
            conns["Y"] = out
            b.insts.append({"name": inst, "cell": cell, "conns": conns})
            through += [f"{inst}/{p}" for p in COMB[cell][0]]
            pool.append(out)
            outs.append(out)
        carry = []
        captured = rng.sample(outs[-4:], 2)
        for net in captured:
            q = b.name("q")
            regs.append(
                {
                    "name": b.name("r"),
                    "cell": "DFFX1",
                    "conns": {"D": net, "CK": leaves[cc].pop(), "Q": q},
                }
            )
            carry.append(q)
        spare += [n for n in outs[:-4]]
    rng.shuffle(spare)
    for r in regs:
        if r["conns"]["D"] is None:
            r["conns"]["D"] = spare.pop()
    b.insts.extend(regs)
    names_r = [r["name"] for r in regs]
    for k in range(PERF_EXCEPTIONS // 2):
        frm = [("cell", n) for n in sorted(rng.sample(names_r, len(names_r) // 4))]
        thr = sorted(rng.sample(through, rng.randint(1, 2)))
        if k % 2 == 0:
            cons["exceptions"].append({"kind": "false", "from": frm, "through": thr})
            frm2 = [("cell", n) for n in sorted(rng.sample(names_r, len(names_r) // 4))]
            cons["exceptions"].append(
                {
                    "kind": "false",
                    "from": frm2,
                    "through": sorted(rng.sample(through, 1)),
                }
            )
        else:
            n = rng.randint(2, 3)
            cons["exceptions"].append(
                {"kind": MCP_SETUP, "n": n, "from": frm, "through": thr}
            )
            cons["exceptions"].append(
                {"kind": MCP_HOLD, "n": n - 1, "from": frm, "through": thr}
            )
    cons["derates"] = [
        {"which": w, "where": "clock", "factor": f} for (w, _), f in _clock_derates(rng)
    ]
    cons["derates"].append(
        {"which": "late", "where": "data", "factor": round(rng.uniform(1.03, 1.1), 3)}
    )
    netlist = {
        "name": "top",
        "inputs": b.inputs,
        "outputs": [],
        "insts": b.insts,
        "assigns": {},
        "_flops": names_r,
        "_latches": [],
        "_gen_flops": [],
    }
    return netlist, cons


# --------------------------------------------------------------------------- case families


def _clock_derates(r):
    return [
        (("early", "clock"), round(r.uniform(0.85, 0.95), 3)),
        (("late", "clock"), round(r.uniform(1.05, 1.15), 3)),
    ]


FAMILIES = {
    "smoke": lambda r: {"gates": 10, "flops": 3, "inputs": 3, "outputs": 2},
    "setup": lambda r: {
        "gates": r.randint(30, 50),
        "flops": r.randint(5, 9),
        "inputs": r.randint(3, 6),
        "outputs": 3,
    },
    "hold": lambda r: {
        "gates": r.randint(30, 50),
        "flops": r.randint(5, 9),
        "inputs": r.randint(3, 6),
        "outputs": 3,
    },
    "cppr": lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(6, 10),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": r.randint(2, 3),
        "reconverge": r.random() < 0.5,
        "derates": _clock_derates(r),
    },
    GENERATED: lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "generated": r.choice(
            [
                ("divide_by", 2),
                ("divide_by", 4),
                ("multiply_by", 2),
                ("edges", [1, 3, 7]),
                ("edges", [3, 5, 9]),
            ]
        ),
        "gen_flops": r.randint(3, 5),
        "cross": 0.3,
    },
    MULTICLOCK: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(4, 6),
        "inputs": 4,
        "outputs": 3,
        "clocks": 2,
        "offset_waveform": True,
        "cross": 0.35,
    },
    MCP_SETUP: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 8),
        "inputs": 4,
        "outputs": 3,
    },
    MCP_HOLD: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 8),
        "inputs": 4,
        "outputs": 3,
        "propagated": True,
    },
    FALSE_PATH: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 8),
        "inputs": 4,
        "outputs": 3,
    },
    "latch": lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 3,
        "outputs": 2,
        "latches": r.randint(2, 3),
    },
    "derate": lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 8),
        "inputs": 4,
        "outputs": 3,
        "propagated": True,
        "derates": [
            (("early", "data"), round(r.uniform(0.85, 0.95), 3)),
            (("late", "data"), round(r.uniform(1.05, 1.15), 3)),
        ],
    },
    "nldm": lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 4,
        "outputs": 3,
        "sdc_units": r.choice([("ns", "pF"), ("ps", "fF")]),
    },
    "unate": lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 6),
        "inputs": 4,
        "outputs": 3,
        "gate_set": ["INVX1", "NAND2X1", "NOR2X1", "XOR2X1", "AOI21X1"],
    },
    SUMMARY: lambda r: {
        "gates": r.randint(40, 70),
        "flops": r.randint(8, 12),
        "inputs": 5,
        "outputs": 4,
        "propagated": True,
    },
    "trace": lambda r: {
        "gates": r.randint(40, 70),
        "flops": r.randint(8, 12),
        "inputs": 5,
        "outputs": 4,
    },
    STRESS: lambda r: {
        "gates": r.randint(45, 70),
        "flops": r.randint(5, 7),
        "inputs": 5,
        "outputs": 4,
        "propagated": True,
        "tree_depth": 3,
        "reconverge": True,
        "generated": r.choice([("divide_by", 2), ("edges", [1, 3, 7])]),
        "gen_flops": 3,
        "latches": 2,
        "cross": 0.25,
        "derates": [
            (("early", "clock"), 0.92),
            (("late", "clock"), 1.08),
            (("early", "data"), 0.95),
            (("late", "data"), 1.06),
        ],
        "exceptions": True,
    },
    LATCH_GEN: lambda r: {
        "gates": r.randint(35, 50),
        "flops": r.randint(4, 6),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "reconverge": True,
        "generated": r.choice([("multiply_by", 2), ("edges", [2, 4, 6])]),
        "gen_flops": 3,
        "latches": 2,
        "latch_source": GENERATED_SOURCE,
        "cross": 0.2,
        "derates": _clock_derates(r),
    },
    FP_MCP: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 8),
        "inputs": 4,
        "outputs": 3,
    },
    MIXED_UNITS: lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 4,
        "outputs": 3,
        "sdc_units": r.choice([("ns", "pF"), ("ps", "fF")]),
    },
    THREE_ORDERS: lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 4,
        "outputs": 3,
    },
    CPPR_DEEP: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(8, 12),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": r.randint(3, 4),
        "reconverge": True,
        "derates": _clock_derates(r),
    },
    CPPR_TIE: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(8, 12),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 3,
        "reconverge": True,
        "derates": _clock_derates(r),
    },
    LATCH_ON_GEN: lambda r: {
        "gates": r.randint(35, 50),
        "flops": r.randint(4, 6),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "reconverge": True,
        "generated": r.choice(
            [
                ("divide_by", 2),
                ("multiply_by", 2),
                ("edges", [1, 3, 7]),
                ("edges", [2, 4, 6]),
            ]
        ),
        "gen_flops": 3,
        "latches": 2,
        "latch_enable": GENERATED_SOURCE,
        "cross": 0.3,
        "derates": _clock_derates(r),
    },
    LATCH_DERATE: lambda r: {
        "gates": r.randint(25, 40),
        "flops": r.randint(4, 7),
        "inputs": 3,
        "outputs": 2,
        "latches": r.randint(2, 3),
        "propagated": True,
        "derates": [
            *_clock_derates(r),
            (("late", "data"), round(r.uniform(1.05, 1.15), 3)),
        ],
    },
    OPPOSITE: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(6, 9),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "inverted": r.randint(2, 3),
        "cross": 0.0,
        "derates": _clock_derates(r),
    },
    GEN_OF_GEN: lambda r: {
        "gates": r.randint(35, 50),
        "flops": r.randint(4, 6),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": r.randint(2, 3),
        "reconverge": r.random() < 0.5,
        "generated": r.choice([("divide_by", 2), ("edges", [1, 3, 7])]),
        "gen_flops": 3,
        "generated2": r.choice([("divide_by", 2), ("edges", [1, 3, 5]), ("multiply_by", 2)]),
        "gen2_flops": 3,
        "cross": 0.45,
        "derates": _clock_derates(r),
    },
    MCP_RATIO: lambda r: {
        "gates": r.randint(30, 45),
        "flops": r.randint(5, 7),
        "inputs": 4,
        "outputs": 2,
        "clocks": 2,
        "cross": 0.45,
        "propagated": True,
    },
    LATCH_GEN_DERATE: lambda r: {
        "gates": r.randint(35, 50),
        "flops": r.randint(4, 6),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "reconverge": True,
        "generated": r.choice([("edges", [2, 4, 6]), ("multiply_by", 2)]),
        "gen_flops": 3,
        "latches": 3,
        "latch_enable": GENERATED_SOURCE,
        "cross": 0.3,
        "derates": [*_clock_derates(r), (("late", "data"), round(r.uniform(1.05, 1.15), 3))],
    },
    PBA: lambda r: {
        "gates": r.randint(40, 60),
        "flops": r.randint(8, 12),
        "inputs": 3,
        "outputs": 2,
        "propagated": True,
        "tree_depth": 2,
        "gate_set": ["NAND2X1", "NOR2X1", "AND2X1", "XOR2X1", "AOI21X1"],
        "derates": [*_clock_derates(r), (("late", "data"), round(r.uniform(1.05, 1.15), 3))],
    },
}
LIB_OPTIONS = {
    "nldm": lambda r: {
        "units": r.choice([("1ps", "ff"), ("1ns", "pf")]),
        "orders": r.choice(["load_first", "mixed"]),
        "span": "narrow",
    },
    "unate": lambda r: {
        "span": "wide",
        "orders": r.choice(["mixed", "slew_first", "load_first"]),
    },
    MIXED_UNITS: lambda r: {
        "units": r.choice([("1ps", "pf"), ("1ns", "ff")]),
        "orders": r.choice(["load_first", "mixed"]),
    },
    THREE_ORDERS: lambda r: {"span": "narrow", "orders": "mixed", "three_orders": True},
    CPPR_TIE: lambda r: {"sym_and": True},
}


def _pick(rng, netlist, cons, want):
    flops = [f for f in netlist["_flops"] if not f.startswith("udiv")]
    roll = rng.random()
    if want == "from":
        if roll < 0.65:
            return [
                ("cell", n)
                for n in rng.sample(flops, min(len(flops), rng.randint(1, 3)))
            ]
        return [("port", rng.choice(cons["input_delay"])["port"])]
    if roll < 0.55:
        return [
            ("cell", n) for n in rng.sample(flops, min(len(flops), rng.randint(1, 3)))
        ]
    if roll < 0.8:
        return [("pin", f"{rng.choice(flops)}/D")]
    return [("port", rng.choice(netlist["outputs"]))]


def _through(rng, netlist, avoid=()):
    pins = [
        f"{i['name']}/{p}"
        for i in netlist["insts"]
        if i["name"].startswith("u")
        for p in i["conns"]
    ]
    return rng.choice([p for p in pins if p not in avoid] or pins)


def add_exceptions(rng, family, netlist, cons):
    ex = []
    if family in (MCP_SETUP, MCP_HOLD, STRESS):
        n = rng.randint(2, 3)
        e = {"kind": MCP_SETUP, "n": n}
        shape = rng.choice(["ft", "f", "t", "th"])
        if "f" in shape:
            e["from"] = _pick(rng, netlist, cons, "from")
        if "h" in shape:
            e["through"] = [_through(rng, netlist)]
        if "t" in shape:
            e["to"] = _pick(rng, netlist, cons, "to")
        ex.append(e)
        if family == MCP_HOLD and rng.random() < 0.5:
            ex.append({**e, "kind": MCP_HOLD, "n": n - 1})
    if family in (FALSE_PATH, STRESS):
        avoid = {p for e in ex for p in e.get("through", [])}
        e = {"kind": "false"}
        shape = rng.choice(["ft", "th", "fh", "h", "t"])
        if "f" in shape:
            e["from"] = _pick(rng, netlist, cons, "from")
        if "h" in shape:
            e["through"] = [
                _through(rng, netlist, avoid) for _ in range(rng.randint(1, 2))
            ]
        if "t" in shape:
            e["to"] = _pick(rng, netlist, cons, "to")
        ex.append(e)
    if family == FP_MCP:
        shared = _through(rng, netlist)
        ex.append({"kind": MCP_SETUP, "n": rng.randint(2, 3), "through": [shared]})
        e = {"kind": "false", "through": [shared]}
        if rng.random() < 0.5:
            e["to"] = _pick(rng, netlist, cons, "to")
        ex.append(e)
    if family == LATCH_ON_GEN:
        e = {
            "kind": MCP_SETUP,
            "n": 2,
            "to": [("cell", n) for n in netlist["_latches"]],
        }
        if rng.random() < 0.5:
            flops = [f for f in netlist["_flops"] if f not in netlist["_gen_flops"]]
            e["from"] = [("cell", n) for n in rng.sample(flops, min(2, len(flops)))]
        ex.append(e)
    if family == LATCH_GEN:
        e = {
            "kind": MCP_SETUP,
            "n": 2,
            "to": [("cell", n) for n in netlist["_latches"]],
        }
        if rng.random() < 0.5:
            e["from"] = [("cell", n) for n in netlist["_gen_flops"]]
        ex.append(e)
    if family == MCP_RATIO:
        a, c = [k["name"] for k in cons["clocks"]][:2]
        if rng.random() < 0.5:
            a, c = c, a
        n = rng.randint(2, 3)
        ends = {"from": [("clock", a)], "to": [("clock", c)]}
        ex.append({"kind": MCP_SETUP, "n": n, **ends})
        ex.append({"kind": MCP_HOLD, "n": rng.randint(1, n - 1), **ends})
    cons["exceptions"] = ex


EXCEPTION_FAMILIES = (MCP_SETUP, MCP_HOLD, FALSE_PATH, FP_MCP, LATCH_GEN, LATCH_ON_GEN, MCP_RATIO)
# Families whose graded fields must not see set_output_delay endpoints, distinct -min input delays,
# so the guard controls of R2 (output delay) and R3 (input -min) keep their sole rejectors.
IO_FREE = {
    CPPR_DEEP, CPPR_TIE, LATCH_GEN, LATCH_ON_GEN, OPPOSITE, LATCH_DERATE, GENERATED, "derate",
    SUMMARY, MCP_HOLD, GEN_OF_GEN, MCP_RATIO, LATCH_CHAIN, LATCH_GEN_DERATE, PBA, PERF,
}


def _isolate_io(cons):
    cons["output_delay"] = []
    for d in cons["input_delay"]:
        d["min"] = d["max"]


def make_case(family: str, seed) -> dict:
    rng = random.Random(f"{family}:{seed}")
    if family in (LATCH_CHAIN, PERF):
        lib = library(rng.randrange(1 << 30))
        build = latch_chain_design if family == LATCH_CHAIN else perf_design
        netlist, cons = build(rng.randrange(1 << 30))
    else:
        spec = FAMILIES[family](rng)
        lib = library(rng.randrange(1 << 30), **LIB_OPTIONS.get(family, lambda r: {})(rng))
        netlist, cons = design(rng.randrange(1 << 30), spec)
        if family in EXCEPTION_FAMILIES or spec.get("exceptions"):
            add_exceptions(rng, family, netlist, cons)
    if family in IO_FREE:
        _isolate_io(cons)
    return {
        "family": family,
        "seed": seed,
        "lib": lib,
        "netlist": netlist,
        "cons": cons,
    }


def texts(case: dict) -> dict:
    return {
        "cells.nldm": library_text(case["lib"]),
        "top.v": netlist_text(case["netlist"]),
        "top.sdc": constraints_text(case["cons"]),
    }


def write(case: dict, root: str) -> None:
    out = Path(root)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in texts(case).items():
        (out / name).write_text(text)


# --------------------------------------------------------------------------- worked example

EXAMPLE = {
    "library_seed": "example:library:0",
    "period": 0.28,
    "fall": 0.15,
    "period2": 0.7,
    "waveform2": [0.1, 0.45],
}


def example_case(params=None) -> dict:
    """The fixed worked design shipped with its exact report under /app/design/example/.

    It exercises the rules the statement leaves to evidence: arrivals kept per launching group, the
    CPPR trace with a reconvergent tie and a common pin carrying opposite transitions, and latch
    borrowing both inside and against the open-window bound with Q launched through D.
    """
    p = {**EXAMPLE, **(params or {})}
    lib = library(p["library_seed"])
    a, bpin = lib["cells"]["AND2X1"]["timing"]
    bpin["tables"] = {
        k: [v[0], [row[:] for row in v[1]]] for k, v in a["tables"].items()
    }
    lib["cells"]["AND2X1"]["pins"]["B"]["capacitance"] = lib["cells"]["AND2X1"]["pins"][
        "A"
    ]["capacitance"]
    insts = [
        ("CLKBUFX4", "xc0", {"A": "clk", "Y": "k0"}),
        ("CLKBUFX4", "xc1", {"A": "k0", "Y": "k1"}),
        ("CLKBUFX4", "xc2", {"A": "k1", "Y": "k2a"}),
        ("CLKBUFX4", "xc3", {"A": "k1", "Y": "k2b"}),
        ("AND2X1", "xm", {"A": "k2a", "B": "k2b", "Y": "km"}),
        ("CLKBUFX4", "xc4", {"A": "km", "Y": "k3"}),
        ("CLKINVX2", "xi0", {"A": "k2a", "Y": "kna"}),
        ("CLKINVX2", "xi1", {"A": "k2b", "Y": "knb"}),
        ("CLKINVX2", "xg", {"A": "clk", "Y": "gn"}),
        ("CLKBUFX4", "xc5", {"A": "clk2", "Y": "q2k"}),
        ("INVX1", "u0", {"A": "e", "Y": "n0"}),
        ("NAND2X1", "u1", {"A": "f0q", "B": "a", "Y": "n1"}),
        ("INVX1", "u2", {"A": "n1", "Y": "n2"}),
        ("XOR2X1", "u3", {"A": "n2", "B": "s0q", "Y": "n3"}),
        ("BUFX2", "u4", {"A": "f1q", "Y": "n4"}),
        ("NOR2X1", "u5", {"A": "n4", "B": "b", "Y": "n5"}),
        ("AND2X1", "u6", {"A": "f2q", "B": "c", "Y": "n6"}),
        ("AOI21X1", "u7", {"A": "n6", "B": "n2", "C": "c", "Y": "n7"}),
        ("XOR2X1", "u8", {"A": "n7", "B": "f4q", "Y": "n8"}),
        ("INVX1", "u9", {"A": "n8", "Y": "n9"}),
        ("NAND2X1", "u10", {"A": "n9", "B": "n6", "Y": "n10"}),
        ("XOR2X1", "u11", {"A": "n10", "B": "n7", "Y": "n11"}),
        ("BUFX2", "u12", {"A": "n11", "Y": "n12"}),
        ("AND2X1", "u13", {"A": "l0q", "B": "l1q", "Y": "n13"}),
        ("BUFX2", "u14", {"A": "n13", "Y": "n14"}),
        ("BUFX2", "u15", {"A": "l1q", "Y": "n15"}),
        ("DFFX1", "f0", {"D": "n0", "CK": "k3", "Q": "f0q"}),
        ("DFFX1", "f1", {"D": "n3", "CK": "k2b", "Q": "f1q"}),
        ("DFFX1", "f2", {"D": "n15", "CK": "k2a", "Q": "f2q"}),
        ("DFFX1", "f3", {"D": "n5", "CK": "knb", "Q": "f3q"}),
        ("DFFX1", "f4", {"D": "n14", "CK": "kna", "Q": "f4q"}),
        ("DFFX1", "s0", {"D": "n4", "CK": "q2k", "Q": "s0q"}),
        ("DLATX1", "l0", {"D": "n12", "G": "gn", "Q": "l0q"}),
        ("DLATX1", "l1", {"D": "n7", "G": "gn", "Q": "l1q"}),
    ]
    inputs = ["clk", "clk2", "a", "b", "c", "e"]
    netlist = {
        "name": "example",
        "inputs": inputs,
        "outputs": ["y0", "y1"],
        "insts": [{"name": n, "cell": c, "conns": k} for c, n, k in insts],
        "assigns": {"y0": "n14", "y1": "n5"},
        "_flops": ["f0", "f1", "f2", "f3", "f4", "s0"],
        "_latches": ["l0", "l1"],
        "_gen_flops": [],
    }
    cons = {
        "units": {"time": "ns", "cap": "pF"},
        "propagated": "all",
        "generated": [],
        "clocks": [
            {
                "name": "clk",
                "port": "clk",
                "period": p["period"],
                "waveform": [0.0, p["fall"]],
            },
            {
                "name": "clk2",
                "port": "clk2",
                "period": p["period2"],
                "waveform": list(p["waveform2"]),
            },
        ],
        "clock_transition": {"clk": 0.03, "clk2": 0.04},
        "input_transition": {
            "clk": 0.02,
            "clk2": 0.025,
            "a": 0.04,
            "b": 0.06,
            "c": 0.03,
            "e": 0.05,
        },
        "input_delay": [
            {"port": "a", "clock": "clk", "max": 0.06, "min": 0.02},
            {"port": "b", "clock": "clk", "max": 0.05, "min": 0.01},
            {"port": "c", "clock": "clk", "max": 0.04, "min": 0.015},
            {"port": "e", "clock": "clk2", "max": 0.08, "min": 0.03},
        ],
        "output_delay": [
            {"port": "y0", "clock": "clk", "max": 0.05, "min": 0.0},
            {"port": "y1", "clock": "clk", "max": 0.04, "min": -0.01},
        ],
        "load": {"y0": 0.004, "y1": 0.006},
        "exceptions": [
            {"kind": MCP_SETUP, "n": 2, "from": [("cell", "f0")]},
            {"kind": "false", "through": ["u8/B"]},
        ],
        "derates": [
            {"which": "early", "where": "clock", "factor": 0.9},
            {"which": "late", "where": "clock", "factor": 1.1},
            {"which": "early", "where": "data", "factor": 0.95},
            {"which": "late", "where": "data", "factor": 1.05},
        ],
    }
    return {
        "family": "example",
        "seed": p["library_seed"],
        "lib": lib,
        "netlist": netlist,
        "cons": cons,
    }


# --------------------------------------------------------------------------- targeted selection

MIN_GAP = 1e-8  # ns; no argmax decision the report depends on may sit closer than this to a tie


def _diff(a, b, field):
    out = 0
    for ep, v in a["endpoints"].items():
        x, y = v[field], b["endpoints"][ep][field]
        if (x is None) != (y is None) or (x is not None and abs(x - y) > 1e-6):
            out += 1
    return out


def _without_exceptions(case, keep=None):
    kept = [e for e in case["cons"]["exceptions"] if keep and keep(e)]
    return {**case, "cons": {**case["cons"], "exceptions": kept}}


def _analyse(case, variant=None):
    return sta_ref.analyse(case["lib"], case["netlist"], case["cons"], variant)


def _same(a, b, tol=1e-6):
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and set(a) == set(b)
            and all(_same(a[k], b[k], tol) for k in a)
        )
    if isinstance(a, list):
        return (
            isinstance(b, list)
            and len(a) == len(b)
            and all(_same(x, y, tol) for x, y in zip(a, b))
        )
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return isinstance(b, (int, float)) and abs(a - b) <= tol
    return a == b


def _gen_latch_relation_differs(case):
    import sta_ref

    ref = sta_ref.Ref(case["lib"], case["netlist"], case["cons"])
    ref.analyse()
    gen = {g["name"]: ref.clock_of[g["source_pin"]] for g in case["cons"]["generated"]}
    for inst in case["netlist"]["_latches"]:
        ep, ck = f"{inst}/D", f"{inst}/G"
        cap, src, _lat, _sl = ref.clk_info(ck, "rise")
        for tr in ("rise", "fall"):
            for tag in ref.darr(ep)[tr]:
                if tag[0] in gen and ref.relation(
                    tag[0], tag[1], cap, src
                ) != ref.relation(gen[tag[0]], tag[1], cap, src):
                    return True
    return False


def _differs(case, report, variant, fields=None):
    other = _analyse(case, variant)
    if fields is None:
        return not _same(report, other)
    return any(_diff(report, other, f) for f in fields)


MOVE = 1e-3  # ns; a targeting predicate's alternative reading must move a graded value at least this far


def _moved(a, b, fields, tol=MOVE):
    out = 0
    for ep, v in a["endpoints"].items():
        for f in fields:
            x, y = v[f], b["endpoints"][ep][f]
            if (x is None) != (y is None) or (x is not None and abs(x - y) >= tol):
                out += 1
                break
    return out


def _borrow_moved(a, b, tol=MOVE):
    return sum(
        1
        for k, v in a["borrow"].items()
        if (v is None) != (b["borrow"][k] is None)
        or (v is not None and abs(v - b["borrow"][k]) >= tol)
    )


def _no_derates(case):
    return {**case, "cons": {**case["cons"], "derates": []}}


def _gog_upstream(case):
    """A check whose CPPR credit sits on a primary-clock pin while one side runs on the generated-of-generated clock."""
    ref = sta_ref.Ref(case["lib"], case["netlist"], case["cons"])
    ref.analyse()
    inner = {g["name"] for g in case["cons"]["generated"]}
    gog = {g for g in inner if ref.gen_master[g] in inner}
    for ep in ref.endpoints():
        if "/" not in ep or "ff" not in ref.cell_of(ep):
            continue
        ck = ep.split("/")[0] + "/CK"
        for tr in sta_ref.TRS:
            for tag in ref.darr(ep)[tr]:
                if tag[0] not in gog and ref.clock_of[ck] not in gog:
                    continue
                launch = ref.launch_of(ep, tr, tag, "late")
                if launch is None:
                    continue
                tl = ref.ctrace(launch, "rise", "late")
                tc = dict(ref.ctrace(ck, "rise", "early"))
                for pin, t in reversed(tl):
                    if pin in tc:
                        rec = ref.carr(pin, t)
                        if (
                            tc[pin] == t
                            and ref.clock_of[pin] not in inner
                            and rec["late"][0] - rec["early"][0] >= MOVE
                        ):
                            return True
                        break
    return False


def _ratio_non_integer(case):
    ps = [sta_ref.frac(k["period"]) for k in case["cons"]["clocks"][:2]]
    hi, lo = max(ps), min(ps)
    return hi / lo != hi // lo


def _latch_chain_ok(case, report):
    ref = sta_ref.Ref(case["lib"], case["netlist"], case["cons"])
    ref.analyse()
    for k, inst in enumerate(case["netlist"]["_latches"]):
        b = report["borrow"].get(f"{inst}/D")
        if b is None or b < MOVE:
            return False
        if k and not any(
            ref.through_latch(f"{inst}/D", tr, tag)
            for tr, tag, _a, _s, _S in ref.latch_borrowers(f"{inst}/D")
        ):
            return False
    return True


def _latch_gen_credit(case):
    ref = sta_ref.Ref(case["lib"], case["netlist"], case["cons"])
    ref.analyse()
    gen = {g["name"] for g in case["cons"]["generated"]}
    for inst in case["netlist"]["_latches"]:
        ep, ck = f"{inst}/D", f"{inst}/G"
        if ref.clock_of[ck] not in gen:
            continue
        for tr in sta_ref.TRS:
            for tag, r in ref.darr(ep)[tr].items():
                chk = ref._seq_check(ep, tr, tag, r)
                if chk is None or chk[2] < MOVE:
                    continue
                launch = ref.launch_of(ep, tr, tag, "late")
                if ref.credit(launch, "late", ck, "rise", "early") >= MOVE:
                    return True
    return False


def _pba_ok(case, report):
    pba = report["pba_setup"]
    moved = [e for e, v in pba.items() if abs(v - report["endpoints"][e]["setup"]) >= MOVE]
    if len(moved) < 2:
        return False
    flat = _analyse(_no_derates(case))
    if not any(
        abs(v - flat["endpoints"][e]["setup"]) >= MOVE for e, v in flat["pba_setup"].items()
    ):
        return False
    other = _analyse(case, sta_ref.PBA_NO_DERATE)
    return any(abs(v - other["pba_setup"].get(e, v + 1)) >= MOVE for e, v in pba.items())


def perf_profile(case):
    """Structural measures the R26 predicate reads: pins, clocks, exceptions, launch groups, cone sizes."""
    nl, cons, lib = case["netlist"], case["cons"], case["lib"]
    pins = len(nl["inputs"]) + len(nl["outputs"]) + sum(len(i["conns"]) for i in nl["insts"])
    ref = sta_ref.Ref(lib, nl, cons)
    groups, launch = set(), []
    for i in nl["insts"]:
        cell = lib["cells"][i["cell"]]
        if "ff" not in cell and "latch" not in cell:
            continue
        q = f"{i['name']}/Q"
        if q in ref.clock_pins:
            continue
        ck = f"{i['name']}/{'CK' if 'ff' in cell else 'G'}"
        clock, src, _lat, _slew = ref.clk_info(ck, "rise")
        groups.add(ref.start_tag(clock, src, {("cell", i["name"]), ("clock", clock)}))
        launch.append(q)
    for d in cons["input_delay"]:
        groups.add(ref.start_tag(d["clock"], "rise", {("port", d["port"]), ("clock", d["clock"])}))
        launch.append(d["port"])
    cone = 0
    for start in launch:
        seen, stack = {start}, [start]
        while stack:
            pin = stack.pop()
            nxt = []
            if "/" in pin and ref.cell_of(pin)["pins"][pin.split("/")[1]]["direction"] == "input":
                cell = ref.cell_of(pin)
                if "ff" not in cell and "latch" not in cell:
                    inst, p = pin.split("/")
                    nxt = [
                        f"{inst}/{t['pin']}"
                        for t in cell["timing"]
                        if t["related_pin"] == p and t["timing_type"] == "combinational"
                    ]
            else:
                nxt = list(ref.sinks.get(ref.net_of[pin], []))
            for n in nxt:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        cone = max(cone, len(seen))
    periods = [sta_ref.frac(k["period"]) for k in cons["clocks"]]
    gens = {g["name"] for g in cons["generated"]}
    return {
        "pins": pins,
        "primary_clocks": len(set(periods)),
        "generated": len(gens),
        "generated_of_generated": sum(
            1 for g in cons["generated"] if ref.gen_master[g["name"]] in gens
        ),
        "through_exceptions": sum(1 for e in cons["exceptions"] if e.get("through")),
        "launch_groups": len(groups),
        "max_cone_fraction": cone / pins,
    }


def _perf_ok(case):
    p = perf_profile(case)
    return (
        p["pins"] >= PERF_PINS
        and p["primary_clocks"] >= PERF_CLOCKS
        and p["generated"] >= 4
        and p["generated_of_generated"] >= 1
        and p["through_exceptions"] >= 40
        and p["launch_groups"] >= 200
        and p["max_cone_fraction"] <= 0.01
    )


def _targeted(family, case, report, diag):
    if family == "setup":
        return _differs(case, report, sta_ref.IDEAL_SETUP_SLEW0, ("setup",)) and _differs(
            case, report, sta_ref.OUTPUT_DELAY_ADDED, ("setup",)
        )
    if family == "hold":
        return _differs(case, report, sta_ref.IDEAL_HOLD_SLEW0, ("hold",)) and _differs(
            case, report, sta_ref.INPUT_MIN_IGNORED, ("hold",)
        )
    if family == CPPR_DEEP:
        return (
            diag["max_credit"] > 1e-3
            and diag["credit_depth"] >= 6
            and _differs(
                case, report, sta_ref.CAPTURE_IN_LAUNCH_MODE, ("setup", "hold")
            )
        )
    if family == CPPR_TIE:
        return diag["max_credit"] > 1e-3 and _differs(
            case, report, sta_ref.TIE_LARGER, ("setup", "hold")
        )
    if family == LATCH_ON_GEN:
        return diag["max_credit"] > 1e-3 and _differs(
            case, report, sta_ref.GEN_AS_MASTER
        )
    if family == LATCH_DERATE:
        return diag["max_borrow"] > 1e-3 and _differs(
            case, report, sta_ref.BORROW_UNBOUNDED, ("setup",)
        )
    if family == "cppr":
        return diag["max_credit"] > 1e-3
    if family == "latch":
        return diag["max_borrow"] > 1e-3
    if family == "nldm":
        return diag["extrapolations"] > 0
    if family == "unate":
        return diag["extrapolations"] == 0
    if family == "trace":
        return bool(report["critical_path"]) and report["critical_path"][0][
            "pin"
        ].endswith("/CK")
    if family == SUMMARY:
        return report["tns_setup"] < 0 and report["wns_hold"] is not None
    if family in (GENERATED, MULTICLOCK):
        return bool(focus(family, case, report))
    if family in (MCP_SETUP, FALSE_PATH):
        return _diff(report, _analyse(_without_exceptions(case)), "setup") > 0
    if family == MCP_HOLD:
        names = focus(family, case, report)
        other = _analyse(case, sta_ref.HOLD_UNSHIFTED)
        return any(
            not _same(report["endpoints"][e]["hold"], other["endpoints"][e]["hold"])
            for e in names
        )
    if family == STRESS:
        base = _analyse(_without_exceptions(case))
        return (
            diag["max_credit"] > 1e-3
            and diag["max_borrow"] > 1e-3
            and _diff(report, base, "setup") > 0
        )
    if family == LATCH_GEN:
        variant = _analyse(case, sta_ref.LATCH_MASTER_EDGE)
        return (
            diag["gen_latch"] > 0
            and diag["max_credit"] > 1e-3
            and not _same(report, variant)
        )
    if family == FP_MCP:
        base = _analyse(_without_exceptions(case, keep=lambda e: e["kind"] != "false"))
        return _diff(report, base, "setup") + _diff(report, base, "hold") > 0
    if family == THREE_ORDERS:
        names = {n for n, t in case["lib"]["templates"].items() if t["vars"] == [LOAD]}
        return {SLEW, LOAD} <= set(diag["extrap_vars"]) and bool(
            names & set(diag["used_templates"])
        )
    if family == OPPOSITE:
        return diag["max_opp"] > 1e-3 and not _same(
            report, _analyse(case, sta_ref.CREDIT_OPPOSITE)
        )
    if family == GEN_OF_GEN:
        other = _analyse(case, sta_ref.GEN_NEAR_SOURCE)
        return _moved(report, other, ("setup", "hold")) > 0 and _gog_upstream(case)
    if family == MCP_RATIO:
        other = _analyse(case, sta_ref.MCP_INTEGER_RATIO)
        return (
            _ratio_non_integer(case)
            and _moved(report, other, ("setup",)) > 0
            and _moved(report, other, ("hold",)) > 0
        )
    if family == LATCH_CHAIN:
        other = _analyse(case, sta_ref.LATCH_CHAIN_NO_THROUGH_D)
        return _latch_chain_ok(case, report) and not _same(report, other)
    if family == LATCH_GEN_DERATE:
        if diag["max_borrow"] < MOVE or not _latch_gen_credit(case):
            return False
        for other in (_analyse(_no_derates(case)), _analyse(case, sta_ref.LATCH_GEN_NO_CPPR)):
            if not _borrow_moved(report, other) or not _moved(report, other, ("setup",)):
                return False
        return True
    if family == PBA:
        return _pba_ok(case, report)
    if family == PERF:
        return _perf_ok(case)
    return True


def _isolated(family, diag):
    """Combined-family behaviours occur only in their own family, so each control fails only there."""
    if family in (GEN_OF_GEN, MCP_RATIO, LATCH_CHAIN, LATCH_GEN_DERATE, PBA, PERF):
        return True
    if family not in (OPPOSITE, LATCH_ON_GEN) and diag["max_opp"] > 0:
        return False
    if family not in (LATCH_GEN, LATCH_ON_GEN) and diag["gen_latch"] > 0:
        return False
    return True


def pick_case(family: str, seed, tries: int = 400):
    """A case of the family that exercises its behaviour, plus its reference report."""
    if family == PERF:
        tries = min(tries, 6)
    import sta_ref

    rng = random.Random(f"pick:{family}:{seed}")
    for _ in range(tries):
        case = make_case(family, rng.randrange(1 << 40))
        report, diag = sta_ref.analyse_with_diagnostics(
            case["lib"], case["netlist"], case["cons"]
        )
        if (
            diag["min_gap"] < MIN_GAP
            or diag["pba_min_gap"] < MIN_GAP
            or diag["tie_hit"]
            or report["wns_setup"] is None
            or not _isolated(family, diag)
        ):
            continue
        if _targeted(family, case, report, diag):
            return case, report
    raise RuntimeError(f"no targeted {family} case within {tries} draws")


MALFORMED = (BAD_LIBRARY, BAD_CELL, BAD_PIN, BAD_OBJECT)


def malformed_case(kind: str, seed) -> dict:
    """Valid smoke texts with exactly one defect of the named kind."""
    case = make_case("smoke", seed)
    t = texts(case)
    gate = next(i for i in case["netlist"]["insts"] if i["name"].startswith("u"))
    if kind == BAD_LIBRARY:
        t["cells.nldm"] = t["cells.nldm"].replace(") ; }", ") }", 1)
    elif kind == BAD_CELL:
        t["top.v"] = t["top.v"].replace(
            f"  {gate['cell']} {gate['name']} (", f"  MUX4X9 {gate['name']} (", 1
        )
    elif kind == BAD_PIN:
        t["top.v"] = t["top.v"].replace(
            f"{gate['name']} (.A(", f"{gate['name']} (.Z(", 1
        )
    else:
        t["top.sdc"] += f"set_false_path -through [get_pins {gate['name']}/ZN]\n"
    return t


def focus(family: str, case: dict, report: dict) -> list:
    """The endpoints an item of this family grades: those its behaviour reaches."""
    import sta_ref

    if family in (GENERATED, MULTICLOCK):
        ref = sta_ref.Ref(case["lib"], case["netlist"], case["cons"])
        ref.analyse()
        names = set()
        for ep in ref.endpoints():
            if "/" not in ep:
                continue
            ck = ep.split("/")[0] + ("/G" if "latch" in ref.cell_of(ep) else "/CK")
            cap = ref.clock_of[ck]
            for _tr, tag, _s, _h, _b in ref.endpoint_checks(ep):
                if (family == GENERATED and cap == GCLK) or (
                    family == MULTICLOCK and tag[0] != cap
                ):
                    names.add(ep)
        return sorted(names)
    base = _analyse(_without_exceptions(case))
    fields = {
        MCP_SETUP: ("setup",),
        MCP_HOLD: ("hold",),
        FALSE_PATH: ("setup", "hold"),
    }[family]
    out = []
    for ep, v in report["endpoints"].items():
        for f in fields:
            x, y = v[f], base["endpoints"][ep][f]
            if (x is None) != (y is None) or (x is not None and abs(x - y) > 1e-6):
                out.append(ep)
                break
    return sorted(out)
