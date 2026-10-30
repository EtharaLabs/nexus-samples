#!/usr/bin/env python3
"""Graph-based static timing analysis for a Liberty NLDM / SDC 2.1 subset.

Reads a Liberty library, a structural Verilog netlist and SDC constraints and
writes a JSON timing report: setup/hold WNS and TNS, per-endpoint slacks, pin
arrivals, latch time borrowing and path-based (re-timed) setup slacks.

All times in the report are nanoseconds.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import sys
from fractions import Fraction

RISE = "rise"
FALL = "fall"
TRANSITIONS = (FALL, RISE)  # kept in string order: "fall" < "rise"

LATE = "late"
EARLY = "early"


class StaError(Exception):
    """Malformed input, undefined object, or a construct outside the subset."""


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------

_TIME_FRACTIONS = {
    "fs": Fraction(1, 10 ** 6),
    "ps": Fraction(1, 10 ** 3),
    "ns": Fraction(1),
    "us": Fraction(10 ** 3),
    "ms": Fraction(10 ** 6),
    "s": Fraction(10 ** 9),
}
_CAP_UNITS = {"ff": 1e-3, "pf": 1.0, "nf": 1e3, "uf": 1e6, "f": 1e12}


def _split_unit(text, what):
    """Split a unit string such as "10ps" into (multiplier, unit name)."""
    m = re.fullmatch(r"\s*([0-9.eE+-]*)\s*([a-zA-Z]+)\s*", text or "")
    if not m:
        raise StaError("%s: bad unit %r" % (what, text))
    mult = Fraction(m.group(1)) if m.group(1) else Fraction(1)
    return mult, m.group(2).lower()


def time_unit_scale(text):
    """Scale factor from a Liberty/SDC time unit string (e.g. "10ps") to ns."""
    mult, unit = _split_unit(text, "time_unit")
    if unit not in _TIME_FRACTIONS:
        raise StaError("unknown time unit: %r" % (text,))
    return float(mult * _TIME_FRACTIONS[unit])


def cap_unit_scale(unit):
    """Scale factor from a capacitance unit name to pF."""
    key = (unit or "").strip().lower()
    if key not in _CAP_UNITS:
        raise StaError("unknown capacitance unit: %r" % (unit,))
    return _CAP_UNITS[key]


# ---------------------------------------------------------------------------
# Liberty parsing
# ---------------------------------------------------------------------------

_LIB_TOKEN = re.compile(
    r"""
      [ \t\r\n]+
    | /\*.*?\*/
    | //[^\n]*
    | "(?:[^"\\]|\\.)*"
    | [()[REDACTED];:,]
    | [^\s()[REDACTED];:,"]+
    """,
    re.X | re.S,
)

_TIME_VARIABLES = {
    "input_net_transition",
    "constrained_pin_transition",
    "related_pin_transition",
    "input_transition_time",
}
_CAP_VARIABLES = {"total_output_net_capacitance", "output_net_capacitance"}


class LibGroup:
    """One Liberty group: `name (args) { ... }`."""

    __slots__ = ("name", "args", "groups", "attrs")

    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.groups = []          # list of LibGroup
        self.attrs = [REDACTED]           # name -> list of value lists

    def sub(self, name):
        return [g for g in self.groups if g.name == name]

    def attr(self, name, default=None):
        """Single value of a simple attribute."""
        vals = self.attrs.get(name)
        if not vals:
            return default
        last = vals[-1]
        return last[0] if len(last) == 1 else " ".join(last)

    def attr_list(self, name):
        """All value lists of a (possibly repeated) attribute."""
        return self.attrs.get(name, [])


def _lib_tokens(text):
    out = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _LIB_TOKEN.match(text, pos)
        if not m:
            raise StaError("bad character in library at offset %d" % pos)
        tok = m.group(0)
        pos = m.end()
        if tok[0] in " \t\r\n" or tok.startswith("/*") or tok.startswith("//"):
            continue
        out.append(tok)
    return out


def _unquote(tok):
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1]
    return tok


def parse_liberty_tree(text):
    """Parse Liberty text into a tree of LibGroup objects."""
    toks = _lib_tokens(text)
    pos = 0

    def expect(tok):
        nonlocal pos
        if pos >= len(toks) or toks[pos] != tok:
            raise StaError("library: expected %r" % tok)
        pos += 1

    def read_args():
        """Read `( a, b )` returning a list of (comma separated) values."""
        nonlocal pos
        expect("(")
        args = []
        cur = []
        while True:
            if pos >= len(toks):
                raise StaError("library: unterminated argument list")
            tok = toks[pos]
            pos += 1
            if tok == ")":
                break
            if tok == ",":
                args.append(" ".join(cur))
                cur = []
            else:
                cur.append(_unquote(tok))
        if cur or args:
            args.append(" ".join(cur))
        return args

    def read_body(group):
        nonlocal pos
        while pos < len(toks):
            tok = toks[pos]
            if tok == "}":
                return
            if tok == ";":
                pos += 1
                continue
            name = _unquote(tok)
            pos += 1
            if pos >= len(toks):
                raise StaError("library: truncated after %r" % name)
            nxt = toks[pos]
            if nxt == "(":
                args = read_args()
                if pos < len(toks) and toks[pos] == "{":
                    pos += 1
                    child = LibGroup(name, args)
                    read_body(child)
                    expect("}")
                    group.groups.append(child)
                else:
                    if pos < len(toks) and toks[pos] == ";":
                        pos += 1
                    group.attrs.setdefault(name, []).append(args)
            elif nxt == ":":
                pos += 1
                vals = []
                while pos < len(toks) and toks[pos] not in (";", "}"):
                    vals.append(_unquote(toks[pos]))
                    pos += 1
                if pos < len(toks) and toks[pos] == ";":
                    pos += 1
                group.attrs.setdefault(name, []).append(vals)
            else:
                raise StaError("library: unexpected token %r after %r" % (nxt, name))

    root = LibGroup("__root__", [])
    read_body(root)
    if pos != len(toks):
        raise StaError("library: trailing text")
    libs = root.sub("library")
    if len(libs) != 1:
        raise StaError("library: expected exactly one library group")
    return libs[0]


def _floats(text):
    out = []
    for piece in re.split(r"[,\s]+", text.strip()):
        if piece:
            try:
                out.append(float(piece))
            except ValueError:
                raise StaError("library: bad number %r" % piece)
    return out


class Table:
    """An NLDM lookup table: 1 or 2 axes of breakpoints plus values."""

    __slots__ = ("axes", "values")

    def __init__(self, axes, values):
        self.axes = axes          # list of (variable_name, [breakpoints])
        self.values = values      # 1-D list, or list of rows

    def lookup(self, args):
        """Interpolate at `args` (a mapping variable name -> value)."""
        if len(self.axes) == 1:
            name, index = self.axes[0]
            i0, i1, t = _interp_weights(index, args[name])
            row = self.values
            return row[i0] + t * (row[i1] - row[i0])
        (n1, idx1), (n2, idx2) = self.axes
        i0, i1, t = _interp_weights(idx1, args[n1])
        j0, j1, u = _interp_weights(idx2, args[n2])
        v00 = self.values[i0][j0]
        v01 = self.values[i0][j1]
        v10 = self.values[i1][j0]
        v11 = self.values[i1][j1]
        low = v00 + u * (v01 - v00)
        high = v10 + u * (v11 - v10)
        return low + t * (high - low)


def _interp_weights(index, value):
    """Bracketing breakpoints and fraction, extrapolating off either end."""
    n = len(index)
    if n == 1:
        return 0, 0, 0.0
    if value <= index[0]:
        i0, i1 = 0, 1
    elif value >= index[-1]:
        i0, i1 = n - 2, n - 1
    else:
        i0 = 0
        hi = n - 1
        while hi - i0 > 1:
            mid = (i0 + hi) // 2
            if index[mid] <= value:
                i0 = mid
            else:
                hi = mid
        i1 = i0 + 1
    span = index[i1] - index[i0]
    if span == 0:
        return i0, i1, 0.0
    return i0, i1, (value - index[i0]) / span


class TableTemplate:
    __slots__ = ("name", "variables", "indices")

    def __init__(self, name, variables, indices):
        self.name = name
        self.variables = variables
        self.indices = indices


class TimingArc:
    """One Liberty `timing` group of an output (or constrained) pin."""

    __slots__ = ("related_pin", "sense", "ttype", "tables")

    def __init__(self, related_pin, sense, ttype, tables):
        self.related_pin = related_pin
        self.sense = sense
        self.ttype = ttype
        self.tables = tables

    @property
    def is_check(self):
        return self.ttype.startswith("setup_") or self.ttype.startswith("hold_")


class PinDef:
    __slots__ = ("name", "direction", "capacitance", "is_clock", "function", "timings")

    def __init__(self, name):
        self.name = name
        self.direction = None
        self.capacitance = 0.0
        self.is_clock = False
        self.function = None
        self.timings = []


class CellDef:
    __slots__ = ("name", "pins", "seq_kind", "data_pin", "clock_pin")

    def __init__(self, name):
        self.name = name
        self.pins = [REDACTED]
        self.seq_kind = None      # None | "ff" | "latch"
        self.data_pin = None
        self.clock_pin = None

    @property
    def is_sequential(self):
        return self.seq_kind is not None

    def pin(self, name):
        try:
            return self.pins[name]
        except KeyError:
            raise StaError("cell %s has no pin %s" % (self.name, name))


class WireLoad:
    __slots__ = ("name", "capacitance", "slope", "fanout_length")

    def __init__(self, name):
        self.name = name
        self.capacitance = 0.0
        self.slope = 0.0
        self.fanout_length = []   # sorted list of (fanout, length)

    def wire_cap(self, fanout):
        """Wire capacitance at `fanout`, extrapolated with `slope`."""
        pts = self.fanout_length
        if not pts:
            return 0.0
        if fanout <= pts[0][0]:
            length = pts[0][1] - (pts[0][0] - fanout) * self.slope
        elif fanout >= pts[-1][0]:
            length = pts[-1][1] + (fanout - pts[-1][0]) * self.slope
        else:
            length = pts[0][1]
            for (f0, l0), (f1, l1) in zip(pts, pts[1:]):
                if f0 <= fanout <= f1:
                    frac = 0.0 if f1 == f0 else (fanout - f0) / (f1 - f0)
                    length = l0 + frac * (l1 - l0)
                    break
        return length * self.capacitance


class Library:
    def __init__(self):
        self.name = None
        self.time_scale = 1.0     # library time unit -> ns
        self.cap_scale = 1.0      # library cap unit -> pF
        self.templates = [REDACTED]
        self.wire_loads = [REDACTED]
        self.default_wire_load = None
        self.cells = [REDACTED]

    def cell(self, name):
        try:
            return self.cells[name]
        except KeyError:
            raise StaError("undefined cell %s" % name)


_TABLE_KINDS = (
    "cell_rise",
    "cell_fall",
    "rise_transition",
    "fall_transition",
    "rise_constraint",
    "fall_constraint",
)

_TIMING_TYPES = {
    "combinational",
    "rising_edge",
    "setup_rising",
    "hold_rising",
    "setup_falling",
    "hold_falling",
}

_SENSES = {"positive_unate", "negative_unate", "non_unate"}


def parse_liberty(path):
    try:
        with open(path, "r", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise StaError("cannot read library: %s" % exc)

    root = parse_liberty_tree(text)
    lib = Library()
    lib.name = root.args[0] if root.args else "lib"
    lib.time_scale = time_unit_scale(root.attr("time_unit", "1ns"))
    clu = root.attr_list("capacitive_load_unit")
    if clu:
        args = clu[-1]
        mult = float(args[0]) if args and args[0] else 1.0
        unit = args[1] if len(args) > 1 else "pf"
        lib.cap_scale = mult * cap_unit_scale(unit)
    lib.default_wire_load = root.attr("default_wire_load")

    for grp in root.sub("lu_table_template"):
        name = grp.args[0] if grp.args else None
        if not name:
            raise StaError("lu_table_template without a name")
        variables, indices = [], []
        for i in (1, 2, 3):
            var = grp.attr("variable_%d" % i)
            if var is None:
                break
            idx = grp.attr_list("index_%d" % i)
            if not idx:
                raise StaError("template %s: missing index_%d" % (name, i))
            vals = _floats(" ".join(idx[-1]))
            if not vals:
                raise StaError("template %s: empty index_%d" % (name, i))
            if var in _TIME_VARIABLES:
                vals = [v * lib.time_scale for v in vals]
            elif var not in _CAP_VARIABLES:
                raise StaError("unsupported table variable %r" % var)
            variables.append(var)
            indices.append(vals)
        if not variables or len(variables) > 2:
            raise StaError("template %s: unsupported variable count" % name)
        lib.templates[name] = TableTemplate(name, variables, indices)

    for grp in root.sub("wire_load"):
        name = grp.args[0] if grp.args else None
        if not name:
            raise StaError("wire_load without a name")
        wl = WireLoad(name)
        wl.capacitance = float(grp.attr("capacitance", 0.0) or 0.0)
        wl.slope = float(grp.attr("slope", 0.0) or 0.0)
        pts = []
        for args in grp.attr_list("fanout_length"):
            if len(args) < 2:
                raise StaError("wire_load %s: bad fanout_length" % name)
            pts.append((float(args[0]), float(args[1])))
        wl.fanout_length = sorted(pts)
        lib.wire_loads[name] = wl

    for grp in root.sub("cell"):
        cell = _parse_cell(lib, grp)
        lib.cells[cell.name] = cell
    return lib


def _parse_table(lib, grp):
    tname = grp.args[0] if grp.args else None
    tmpl = lib.templates.get(tname)
    if tmpl is None:
        raise StaError("undefined lu_table_template %r" % tname)
    rows = grp.attr_list("values")
    if not rows:
        raise StaError("table %s: missing values" % tname)
    raw = [_floats(piece) for piece in rows[-1]]
    scale = lib.time_scale
    if len(tmpl.variables) == 1:
        flat = [v * scale for row in raw for v in row]
        if len(flat) != len(tmpl.indices[0]):
            raise StaError("table %s: value count mismatch" % tname)
        return Table([(tmpl.variables[0], tmpl.indices[0])], flat)
    if len(raw) != len(tmpl.indices[0]):
        raise StaError("table %s: row count mismatch" % tname)
    values = []
    for row in raw:
        if len(row) != len(tmpl.indices[1]):
            raise StaError("table %s: column count mismatch" % tname)
        values.append([v * scale for v in row])
    axes = [(tmpl.variables[0], tmpl.indices[0]), (tmpl.variables[1], tmpl.indices[1])]
    return Table(axes, values)


def _parse_cell(lib, grp):
    name = grp.args[0] if grp.args else None
    if not name:
        raise StaError("cell without a name")
    cell = CellDef(name)

    for kind in ("ff", "latch"):
        for seq in grp.sub(kind):
            if cell.seq_kind is not None:
                raise StaError("cell %s: multiple sequential groups" % name)
            cell.seq_kind = kind
            clk_attr = "clocked_on" if kind == "ff" else "enable"
            dat_attr = "next_state" if kind == "ff" else "data_in"
            clk = seq.attr(clk_attr)
            dat = seq.attr(dat_attr)
            if not clk or not dat:
                raise StaError("cell %s: incomplete %s group" % (name, kind))
            cell.clock_pin = clk.strip().lstrip("!").strip()
            cell.data_pin = dat.strip().lstrip("!").strip()

    for pgrp in grp.sub("pin"):
        for pname in (pgrp.args or []):
            pin = PinDef(pname)
            pin.direction = (pgrp.attr("direction") or "").strip()
            if pin.direction not in ("input", "output"):
                raise StaError("pin %s/%s: unsupported direction" % (name, pname))
            cap = pgrp.attr("capacitance")
            pin.capacitance = float(cap) if cap is not None else 0.0
            clk = (pgrp.attr("clock") or "false").strip().lower()
            pin.is_clock = clk == "true"
            pin.function = pgrp.attr("function")
            for tgrp in pgrp.sub("timing"):
                pin.timings.append(_parse_timing(lib, name, pname, tgrp))
            cell.pins[pname] = pin

    if cell.seq_kind is not None:
        cell.pin(cell.clock_pin)
        cell.pin(cell.data_pin)
    return cell


def _parse_timing(lib, cell_name, pin_name, tgrp):
    related = tgrp.attr("related_pin")
    if not related:
        raise StaError("timing group on %s/%s: no related_pin" % (cell_name, pin_name))
    related = related.strip()
    ttype = (tgrp.attr("timing_type") or "combinational").strip()
    if ttype not in _TIMING_TYPES:
        raise StaError("unsupported timing_type %r" % ttype)
    sense = tgrp.attr("timing_sense")
    sense = sense.strip() if sense else None
    if sense is not None and sense not in _SENSES:
        raise StaError("unsupported timing_sense %r" % sense)
    tables = [REDACTED]
    for kind in _TABLE_KINDS:
        for sub in tgrp.sub(kind):
            tables[kind] = _parse_table(lib, sub)
    return TimingArc(related, sense, ttype, tables)


# ---------------------------------------------------------------------------
# Verilog parsing
# ---------------------------------------------------------------------------

_V_TOKEN = re.compile(
    r"""
      [ \t\r\n]+
    | /\*.*?\*/
    | //[^\n]*
    | [A-Za-z_][A-Za-z0-9_$]*
    | \\[^\s]+
    | [0-9][0-9a-zA-Z_'.]*
    | [(),;.=\[\]:[REDACTED]]
    """,
    re.X | re.S,
)

_V_KEYWORDS = ("input", "output", "inout", "wire", "assign", "endmodule")


class Instance:
    __slots__ = ("name", "cell", "conns")

    def __init__(self, name, cell):
        self.name = name
        self.cell = cell          # CellDef
        self.conns = [REDACTED]           # pin name -> net name


class Netlist:
    def __init__(self):
        self.module = None
        self.inputs = []
        self.outputs = []
        self.nets = set()
        self.instances = [REDACTED]       # name -> Instance
        self.port_assign = [REDACTED]     # output port -> net name


def parse_verilog(path, lib):
    try:
        with open(path, "r", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise StaError("cannot read netlist: %s" % exc)

    toks = []
    pos = 0
    while pos < len(text):
        m = _V_TOKEN.match(text, pos)
        if not m:
            raise StaError("netlist: bad character at offset %d" % pos)
        tok = m.group(0)
        pos = m.end()
        if tok[0] in " \t\r\n" or tok.startswith("/*") or tok.startswith("//"):
            continue
        toks.append(tok)

    nl = Netlist()
    i = 0

    def peek(off=0):
        return toks[i + off] if i + off < len(toks) else None

    def take(expected=None):
        nonlocal i
        if i >= len(toks):
            raise StaError("netlist: unexpected end of file")
        tok = toks[i]
        if expected is not None and tok != expected:
            raise StaError("netlist: expected %r, found %r" % (expected, tok))
        i += 1
        return tok

    if peek() != "module":
        raise StaError("netlist: does not start with a module declaration")
    take("module")
    nl.module = take()
    if peek() == "(":
        take("(")
        while peek() != ")":
            tok = take()
            if tok != ",":
                nl.nets.add(tok)
        take(")")
    take(";")

    while True:
        tok = peek()
        if tok is None:
            raise StaError("netlist: missing endmodule")
        if tok == "endmodule":
            take()
            break
        if tok in ("input", "output", "inout", "wire"):
            take()
            if peek() == "[":
                raise StaError("netlist: vector declarations are not supported")
            names = []
            while peek() != ";":
                name = take()
                if name != ",":
                    names.append(name)
            take(";")
            nl.nets.update(names)
            if tok == "input":
                nl.inputs.extend(names)
            elif tok == "output":
                nl.outputs.extend(names)
            elif tok == "inout":
                raise StaError("netlist: inout ports are not supported")
        elif tok == "assign":
            take()
            lhs = take()
            take("=")
            rhs = take()
            take(";")
            if lhs not in nl.outputs:
                raise StaError("netlist: assign to %r which is not an output" % lhs)
            nl.port_assign[lhs] = rhs
        elif re.fullmatch(r"[A-Za-z_\\][A-Za-z0-9_$]*", tok):
            cell_name = take()
            inst_name = take()
            cell = lib.cell(cell_name)
            inst = Instance(inst_name, cell)
            take("(")
            while peek() != ")":
                if peek() == ",":
                    take()
                    continue
                take(".")
                pin_name = take()
                take("(")
                net = take()
                if net == ")":
                    raise StaError("netlist: empty connection on %s/%s"
                                   % (inst_name, pin_name))
                take(")")
                cell.pin(pin_name)
                if pin_name in inst.conns:
                    raise StaError("netlist: pin %s/%s connected twice"
                                   % (inst_name, pin_name))
                inst.conns[pin_name] = net
            take(")")
            take(";")
            if inst_name in nl.instances:
                raise StaError("netlist: duplicate instance %s" % inst_name)
            nl.instances[inst_name] = inst
        else:
            raise StaError("netlist: unexpected token %r" % tok)

    if i != len(toks):
        raise StaError("netlist: trailing text after endmodule")

    for inst in nl.instances.values():
        for net in inst.conns.values():
            if net not in nl.nets:
                raise StaError("netlist: undeclared net %r on instance %s"
                               % (net, inst.name))
    for port, net in nl.port_assign.items():
        if net not in nl.nets:
            raise StaError("netlist: undeclared net %r assigned to %s" % (net, port))
    return nl


# ---------------------------------------------------------------------------
# SDC parsing (into word lists; interpreted once the design exists)
# ---------------------------------------------------------------------------

class Word:
    """One SDC word: a bare string, a braced list, or a bracketed command."""

    __slots__ = ("kind", "text", "items")

    def __init__(self, kind, text=None, items=None):
        self.kind = kind          # "str" | "list" | "cmd"
        self.text = text
        self.items = items or []

    def as_str(self):
        if self.kind != "str":
            raise StaError("sdc: expected a plain value")
        return self.text

    def __repr__(self):
        if self.kind == "str":
            return self.text
        return "%s(%s)" % (self.kind, " ".join(repr(w) for w in self.items))


class _SdcLexer:
    """Splits SDC text into commands, each a list of Words.

    Braced lists and bracketed object queries are lexed by a nested lexer over
    the group's inner text, so nesting needs no state in the caller.
    """

    def __init__(self, text):
        self.text = text
        self.pos = 0

    def commands(self):
        """Top-level commands, separated by newlines or semicolons."""
        out = []
        current = []
        for word, ended in self._scan():
            if ended:
                if current:
                    out.append(current)
                    current = []
            else:
                current.append(word)
        if current:
            out.append(current)
        return out

    def words(self):
        """Every word of a nested fragment, ignoring separators."""
        return [word for word, ended in self._scan() if not ended]

    def _scan(self):
        """Yield (word, False) for words and (None, True) at a separator."""
        while True:
            self._skip_blanks()
            if self.pos >= len(self.text):
                return
            if self.text[self.pos] in "\n;":
                self.pos += 1
                yield None, True
            else:
                yield self._word(), False

    def _skip_blanks(self):
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == "\\" and self.pos + 1 < len(text) and text[self.pos + 1] == "\n":
                self.pos += 2          # line continuation
            elif ch in " \t\r":
                self.pos += 1
            elif ch == "#":
                while self.pos < len(text) and text[self.pos] != "\n":
                    self.pos += 1
            else:
                return

    def _balanced(self, open_ch, close_ch):
        """Consume a {...} or [...] group and return its inner text."""
        text = self.text
        depth = 0
        start = self.pos
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    inner = text[start + 1:self.pos]
                    self.pos += 1
                    return inner
            elif ch == "\\":
                self.pos += 1
            self.pos += 1
        raise StaError("sdc: unbalanced %r" % open_ch)

    def _word(self):
        text = self.text
        ch = text[self.pos]
        if ch == "{":
            return Word("list", items=_SdcLexer(self._balanced("{", "}")).words())
        if ch == "[":
            return Word("cmd", items=_SdcLexer(self._balanced("[", "]")).words())
        if ch == '"':
            self.pos += 1
            start = self.pos
            while self.pos < len(text) and text[self.pos] != '"':
                self.pos += 1
            if self.pos >= len(text):
                raise StaError("sdc: unterminated string")
            out = text[start:self.pos]
            self.pos += 1
            return Word("str", text=out)
        start = self.pos
        while self.pos < len(text) and text[self.pos] not in " \t\r\n;[{":
            self.pos += 1
        if self.pos == start:
            raise StaError("sdc: unexpected character %r" % ch)
        return Word("str", text=text[start:self.pos])


def parse_sdc(path):
    """Read an SDC file and tokenize it into commands of Words."""
    try:
        with open(path, "r", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise StaError("cannot read sdc: %s" % exc)
    return _SdcLexer(text).commands()


# ---------------------------------------------------------------------------
# design: pins, nets, loads and the timing graph
# ---------------------------------------------------------------------------

class PinNode:
    """A timing-graph node: an instance pin or a top-level port."""

    __slots__ = ("id", "inst", "pname", "pdef", "kind", "net", "fanin", "load_cap")

    def __init__(self, pid, kind):
        self.id = pid
        self.inst = None          # Instance, or None for ports
        self.pname = None
        self.pdef = None          # PinDef, or None for ports
        self.kind = kind          # "in_port" | "out_port" | "cell_in" | "cell_out"
        self.net = None           # net this pin drives (drivers) or sits on (loads)
        self.fanin = []           # [(source pin id, TimingArc)] for cell outputs
        self.load_cap = 0.0       # load of the driven net, for driver pins

    @property
    def is_driver(self):
        return self.kind in ("in_port", "cell_out")


class Design:
    def __init__(self, lib, netlist):
        self.lib = lib
        self.netlist = netlist
        self.pins = [REDACTED]            # pin id -> PinNode
        self.net_driver = [REDACTED]      # net -> pin id
        self.net_loads = [REDACTED]       # net -> [pin id]
        self.net_ports = [REDACTED]       # net -> [output port name]
        self.order = []           # pin ids in topological order
        self.succs = [REDACTED]
        self.ports = set(netlist.inputs) | set(netlist.outputs)
        self._build()

    # -- construction -----------------------------------------------------
    def _build(self):
        nl = self.netlist
        for net in nl.nets:
            self.net_loads[net] = []
            self.net_ports[net] = []

        for port in nl.inputs:
            node = PinNode(port, "in_port")
            node.net = port
            self.pins[port] = node
            self._set_driver(port, port)

        for inst in nl.instances.values():
            for pname, net in inst.conns.items():
                pdef = inst.cell.pin(pname)
                pid = "%s/%s" % (inst.name, pname)
                node = PinNode(pid, "cell_out" if pdef.direction == "output" else "cell_in")
                node.inst = inst
                node.pname = pname
                node.pdef = pdef
                node.net = net
                self.pins[pid] = node
                if pdef.direction == "output":
                    self._set_driver(net, pid)
                else:
                    self.net_loads[net].append(pid)

        for port in nl.outputs:
            node = PinNode(port, "out_port")
            net = nl.port_assign.get(port, port)
            if net not in nl.nets:
                raise StaError("netlist: output port %s has no source net" % port)
            node.net = net
            self.pins[port] = node
            self.net_ports[net].append(port)

        for inst in nl.instances.values():
            for pname, pdef in inst.cell.pins.items():
                if pdef.direction != "output" or pname not in inst.conns:
                    continue
                pid = "%s/%s" % (inst.name, pname)
                node = self.pins[pid]
                for arc in pdef.timings:
                    if arc.is_check:
                        continue
                    src = arc.related_pin
                    inst.cell.pin(src)
                    if src not in inst.conns:
                        continue
                    node.fanin.append(("%s/%s" % (inst.name, src), arc))
                node.fanin.sort(key=lambda item: item[0])

        self._compute_loads()
        self._order_pins()

    def _set_driver(self, net, pid):
        if net in self.net_driver:
            raise StaError("netlist: net %s has multiple drivers" % net)
        self.net_driver[net] = pid

    def _compute_loads(self):
        lib = self.lib
        wl = None
        if lib.default_wire_load:
            wl = lib.wire_loads.get(lib.default_wire_load)
            if wl is None:
                raise StaError("undefined default_wire_load %r" % lib.default_wire_load)
        for net in self.netlist.nets:
            cap = 0.0
            for pid in self.net_loads[net]:
                cap += self.pins[pid].pdef.capacitance
            fanout = len(self.net_loads[net]) + len(self.net_ports[net])
            if wl is not None:
                cap += wl.wire_cap(fanout)
            drv = self.net_driver.get(net)
            if drv is not None:
                self.pins[drv].load_cap = cap

    def add_port_loads(self, port_loads):
        """Add `set_load` port capacitances to their nets (called after SDC)."""
        for net, ports in self.net_ports.items():
            extra = sum(port_loads.get(p, 0.0) for p in ports)
            drv = self.net_driver.get(net)
            if extra and drv is not None:
                self.pins[drv].load_cap += extra

    def _order_pins(self):
        succs = {pid: [] for pid in self.pins}
        indeg = {pid: 0 for pid in self.pins}

        def link(a, b):
            succs[a].append(b)
            indeg[b] += 1

        for pid, node in self.pins.items():
            if node.is_driver:
                for load in self.net_loads.get(node.net, ()):
                    link(pid, load)
                for port in self.net_ports.get(node.net, ()):
                    link(pid, port)
            for src, _arc in node.fanin:
                link(src, pid)

        ready = [pid for pid, deg in indeg.items() if deg == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            pid = heapq.heappop(ready)
            order.append(pid)
            for nxt in succs[pid]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    heapq.heappush(ready, nxt)
        if len(order) != len(self.pins):
            # A combinational loop: append the rest deterministically so that
            # analysis still terminates.
            left = sorted(pid for pid in self.pins if indeg[pid] > 0)
            order.extend(left)
        self.order = order
        self.succs = succs

    # -- queries ----------------------------------------------------------
    def pin(self, pid):
        try:
            return self.pins[pid]
        except KeyError:
            raise StaError("undefined pin %s" % pid)

    def seq_instances(self):
        for name in sorted(self.netlist.instances):
            inst = self.netlist.instances[name]
            if inst.cell.is_sequential:
                yield inst


# ---------------------------------------------------------------------------
# SDC interpretation
# ---------------------------------------------------------------------------

class Clock:
    """A primary or generated clock with its waveform in nanoseconds."""

    def __init__(self, name):
        self.name = name
        self.period = None        # Fraction
        self.rise = None          # Fraction
        self.fall = None          # Fraction
        self.sources = []         # pin ids the clock is defined on
        self.propagated = False
        self.transition = 0.0     # set_clock_transition
        self.generated = None     # GeneratedSpec for generated clocks
        self.master = None        # Clock

    def edge(self, tag):
        return self.rise if tag == "r" else self.fall

    def __repr__(self):
        return "Clock(%s)" % self.name


class GeneratedSpec:
    __slots__ = ("source_pin", "mode", "value", "edges", "master_name")

    def __init__(self, source_pin, mode, value, edges, master_name):
        self.source_pin = source_pin
        self.mode = mode          # "divide_by" | "multiply_by" | "edges"
        self.value = value
        self.edges = edges
        self.master_name = master_name


class IoDelay:
    __slots__ = ("clock", "maxv", "minv")

    def __init__(self, clock):
        self.clock = clock
        self.maxv = None
        self.minv = None

    def late(self):
        return self.maxv if self.maxv is not None else self.minv

    def early(self):
        return self.minv if self.minv is not None else self.maxv


class PathException:
    __slots__ = ("kind", "setup", "hold", "mult", "frm", "to", "through", "order")

    def __init__(self, kind, order):
        self.kind = kind          # "false" | "mcp"
        self.setup = True
        self.hold = True
        self.mult = 1
        self.frm = None           # set of (type, name) or None
        self.to = None
        self.through = []         # list of sets
        self.order = order

    @property
    def specificity(self):
        def rank(objs):
            if objs is None:
                return 0
            return 1 if all(t == "clock" for t, _ in objs) else 2
        return (rank(self.frm) + rank(self.to) + (1 if self.through else 0), self.order)


class Sdc:
    def __init__(self):
        self.time_scale = Fraction(1)
        self.cap_scale = 1.0      # SDC capacitance -> library capacitive_load_unit
        self.clocks = [REDACTED]
        self.input_transition = [REDACTED]
        self.input_delays = [REDACTED]    # port -> {clock name: IoDelay}
        self.output_delays = [REDACTED]
        self.loads = [REDACTED]
        self.exceptions = []
        self.derate = {(LATE, "clock"): 1.0, (EARLY, "clock"): 1.0,
                       (LATE, "data"): 1.0, (EARLY, "data"): 1.0}

    def clock(self, name):
        try:
            return self.clocks[name]
        except KeyError:
            raise StaError("undefined clock %s" % name)


_QUERY_COMMANDS = {"get_ports", "get_pins", "get_cells", "get_clocks", "all_clocks",
                   "all_inputs", "all_outputs"}


def _glob_filter(patterns, names, kind):
    import fnmatch

    out = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            hits = [n for n in names if fnmatch.fnmatchcase(n, pat)]
            if not hits:
                raise StaError("no %s matches %r" % (kind, pat))
            out.extend(sorted(hits))
        else:
            if pat not in names:
                raise StaError("undefined %s %s" % (kind, pat))
            out.append(pat)
    return out


class SdcInterp:
    """Executes SDC commands against a design, filling in an Sdc object."""

    def __init__(self, design, sdc):
        self.design = design
        self.sdc = sdc

    # -- object queries ---------------------------------------------------
    def flatten(self, word):
        """Expand a Word into a list of (type, name) objects."""
        if word.kind == "str":
            return [self._guess(word.text)]
        if word.kind == "list":
            out = []
            for item in word.items:
                out.extend(self.flatten(item))
            return out
        return self._query(word.items)

    def _guess(self, name):
        if name in self.design.ports:
            return ("port", name)
        if name in self.design.pins:
            return ("pin", name)
        if name in self.design.netlist.instances:
            return ("cell", name)
        if name in self.sdc.clocks:
            return ("clock", name)
        raise StaError("undefined object %s" % name)

    def _query(self, items):
        if not items:
            raise StaError("sdc: empty object query")
        cmd = items[0].as_str()
        if cmd not in _QUERY_COMMANDS:
            raise StaError("unsupported object query %r" % cmd)
        patterns = []
        for word in items[1:]:
            if word.kind == "str":
                if word.text.startswith("-"):
                    continue
                patterns.append(word.text)
            elif word.kind == "list":
                for sub in word.items:
                    patterns.append(sub.as_str())
            else:
                raise StaError("sdc: nested query in %r" % cmd)
        design = self.design
        if cmd == "all_clocks":
            return [("clock", name) for name in self.sdc.clocks]
        if cmd == "all_inputs":
            return [("port", p) for p in design.netlist.inputs]
        if cmd == "all_outputs":
            return [("port", p) for p in design.netlist.outputs]
        if cmd == "get_ports":
            return [("port", n) for n in _glob_filter(patterns, design.ports, "port")]
        if cmd == "get_pins":
            names = [p for p in design.pins if "/" in p]
            return [("pin", n) for n in _glob_filter(patterns, names, "pin")]
        if cmd == "get_cells":
            names = design.netlist.instances.keys()
            return [("cell", n) for n in _glob_filter(patterns, names, "cell")]
        if cmd == "get_clocks":
            return [("clock", n) for n in _glob_filter(patterns, self.sdc.clocks, "clock")]
        raise StaError("unsupported object query %r" % cmd)

    def clock_arg(self, word, command):
        """Resolve a single-clock argument, where a bare word names a clock."""
        if word.kind == "str":
            if word.text not in self.sdc.clocks:
                raise StaError("%s: undefined clock %s" % (command, word.text))
            return word.text
        objs = self.flatten(word)
        if len(objs) != 1 or objs[0][0] != "clock":
            raise StaError("%s: expected exactly one clock" % command)
        return objs[0][1]

    # -- helpers ----------------------------------------------------------
    def _time(self, word):
        return float(Fraction(word.as_str()) * self.sdc.time_scale)

    def _frac_time(self, word):
        return Fraction(word.as_str()) * self.sdc.time_scale

    def _cap(self, word):
        return float(word.as_str()) * self.sdc.cap_scale

    @staticmethod
    def _int(word):
        text = word.as_str()
        try:
            value = float(text)
        except ValueError:
            raise StaError("sdc: expected a number, found %r" % text)
        if value != int(value):
            raise StaError("sdc: expected an integer, found %r" % text)
        return int(value)

    def ports_only(self, objs, command):
        out = []
        for kind, name in objs:
            if kind != "port":
                raise StaError("%s: only ports are supported, got %s" % (command, name))
            out.append(name)
        return out

    # -- command dispatch -------------------------------------------------
    def run(self, commands):
        for words in commands:
            name = words[0].as_str()
            handler = getattr(self, "cmd_" + name, None)
            if handler is None:
                raise StaError("unsupported SDC command %r" % name)
            handler(words[1:])

    def cmd_set_units(self, args):
        i = 0
        while i < len(args):
            opt = args[i].as_str()
            if opt not in ("-time", "-capacitance", "-resistance", "-voltage",
                           "-current", "-power"):
                raise StaError("set_units: unsupported option %r" % opt)
            if i + 1 >= len(args):
                raise StaError("set_units: missing value for %s" % opt)
            mult, unit = _split_unit(args[i + 1].as_str(), opt)
            if opt == "-time":
                if unit not in _TIME_FRACTIONS:
                    raise StaError("set_units: unknown time unit %r" % unit)
                # SDC times are scaled exactly: clock edges must stay rational.
                self.sdc.time_scale = Fraction(mult) * _TIME_FRACTIONS[unit]
            elif opt == "-capacitance":
                self.sdc.cap_scale = (float(mult) * cap_unit_scale(unit)
                                      / self.design.lib.cap_scale)
            i += 2

    def cmd_create_clock(self, args):
        name = None
        period = None
        waveform = None
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt == "-name":
                name = args[i + 1].as_str()
                i += 2
            elif opt == "-period":
                period = self._frac_time(args[i + 1])
                i += 2
            elif opt == "-waveform":
                wf = args[i + 1]
                if wf.kind != "list":
                    raise StaError("create_clock: -waveform needs a list")
                waveform = [self._frac_time(w) for w in wf.items]
                i += 2
            elif opt == "-add":
                i += 1
            elif opt is not None and opt.startswith("-"):
                raise StaError("create_clock: unsupported option %r" % opt)
            else:
                objs.extend(self.flatten(word))
                i += 1
        if period is None or period <= 0:
            raise StaError("create_clock: missing or non-positive -period")
        sources = [n for kind, n in objs if kind in ("port", "pin")]
        if name is None:
            if not sources:
                raise StaError("create_clock: no name and no source")
            name = sources[0]
        if name in self.sdc.clocks:
            raise StaError("create_clock: clock %s already defined" % name)
        clk = Clock(name)
        clk.period = period
        if waveform:
            if len(waveform) != 2:
                raise StaError("create_clock: -waveform must have two edges")
            clk.rise, clk.fall = waveform[0], waveform[1]
        else:
            clk.rise, clk.fall = Fraction(0), period / 2
        clk.sources = sources
        for pid in sources:
            if pid not in self.design.pins:
                raise StaError("create_clock: undefined source %s" % pid)
        self.sdc.clocks[name] = clk

    def cmd_create_generated_clock(self, args):
        name = None
        source = None
        mode = None
        value = None
        edges = None
        master = None
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt == "-name":
                name = args[i + 1].as_str()
                i += 2
            elif opt == "-source":
                src = self.flatten(args[i + 1])
                if len(src) != 1 or src[0][0] not in ("pin", "port"):
                    raise StaError("create_generated_clock: -source needs one pin")
                source = src[0][1]
                i += 2
            elif opt in ("-divide_by", "-multiply_by"):
                mode = opt[1:]
                value = self._int(args[i + 1])
                if value < 1:
                    raise StaError("create_generated_clock: bad %s" % opt)
                i += 2
            elif opt == "-edges":
                wf = args[i + 1]
                if wf.kind != "list":
                    raise StaError("create_generated_clock: -edges needs a list")
                edges = [self._int(w) for w in wf.items]
                if len(edges) != 3 or any(e < 1 for e in edges):
                    raise StaError("create_generated_clock: -edges needs three edges")
                mode = "edges"
                i += 2
            elif opt == "-master_clock":
                master = self.clock_arg(args[i + 1], "create_generated_clock")
                i += 2
            elif opt in ("-add", "-combinational"):
                i += 1
            elif opt is not None and opt.startswith("-"):
                raise StaError("create_generated_clock: unsupported option %r" % opt)
            else:
                objs.extend(self.flatten(word))
                i += 1
        if source is None or mode is None:
            raise StaError("create_generated_clock: needs -source and a modifier")
        sources = [n for kind, n in objs if kind in ("port", "pin")]
        if not sources:
            raise StaError("create_generated_clock: no object to define the clock on")
        if name is None:
            name = sources[0]
        if name in self.sdc.clocks:
            raise StaError("create_generated_clock: clock %s already defined" % name)
        clk = Clock(name)
        clk.sources = sources
        clk.generated = GeneratedSpec(source, mode, value, edges, master)
        for pid in sources:
            if pid not in self.design.pins:
                raise StaError("create_generated_clock: undefined source %s" % pid)
        if source not in self.design.pins:
            raise StaError("create_generated_clock: undefined -source pin %s" % source)
        self.sdc.clocks[name] = clk

    def cmd_set_propagated_clock(self, args):
        objs = []
        for word in args:
            objs.extend(self.flatten(word))
        for kind, name in objs:
            if kind == "clock":
                self.sdc.clock(name).propagated = True
            elif kind in ("port", "pin"):
                hit = False
                for clk in self.sdc.clocks.values():
                    if name in clk.sources:
                        clk.propagated = True
                        hit = True
                if not hit:
                    raise StaError("set_propagated_clock: %s is not a clock source" % name)
            else:
                raise StaError("set_propagated_clock: unsupported object %s" % name)

    def cmd_set_clock_transition(self, args):
        value = None
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt in ("-rise", "-fall", "-min", "-max"):
                i += 1
            elif value is None and word.kind == "str" and not opt.startswith("-"):
                value = self._time(word)
                i += 1
            else:
                objs.extend(self.flatten(word))
                i += 1
        if value is None:
            raise StaError("set_clock_transition: missing value")
        for kind, name in objs:
            if kind != "clock":
                raise StaError("set_clock_transition: expected clocks")
            self.sdc.clock(name).transition = value

    def cmd_set_input_transition(self, args):
        value = None
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt in ("-rise", "-fall", "-min", "-max"):
                i += 1
            elif value is None and word.kind == "str" and not opt.startswith("-"):
                value = self._time(word)
                i += 1
            else:
                objs.extend(self.flatten(word))
                i += 1
        if value is None:
            raise StaError("set_input_transition: missing value")
        for port in self.ports_only(objs, "set_input_transition"):
            self.sdc.input_transition[port] = value

    def _io_delay(self, args, command, table):
        clock = None
        value = None
        is_max = False
        is_min = False
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt == "-clock":
                clock = self.clock_arg(args[i + 1], command)
                i += 2
            elif opt == "-max":
                is_max = True
                i += 1
            elif opt == "-min":
                is_min = True
                i += 1
            elif opt in ("-add_delay", "-rise", "-fall", "-network_latency_included",
                         "-source_latency_included", "-level_sensitive"):
                i += 1
            elif opt == "-clock_fall":
                raise StaError("%s: -clock_fall is not supported" % command)
            elif opt is not None and opt.startswith("-") and not _is_number(opt):
                raise StaError("%s: unsupported option %r" % (command, opt))
            elif value is None and word.kind == "str":
                value = self._time(word)
                i += 1
            else:
                objs.extend(self.flatten(word))
                i += 1
        if value is None:
            raise StaError("%s: missing delay value" % command)
        if clock is None:
            raise StaError("%s: -clock is required" % command)
        self.sdc.clock(clock)
        for port in self.ports_only(objs, command):
            entry = table.setdefault(port, [REDACTED]).get(clock)
            if entry is None:
                entry = IoDelay(clock)
                table[port][clock] = entry
            if is_max or not is_min:
                entry.maxv = value
            if is_min or not is_max:
                entry.minv = value

    def cmd_set_input_delay(self, args):
        self._io_delay(args, "set_input_delay", self.sdc.input_delays)

    def cmd_set_output_delay(self, args):
        self._io_delay(args, "set_output_delay", self.sdc.output_delays)

    def cmd_set_load(self, args):
        value = None
        objs = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt in ("-max", "-min", "-pin_load", "-wire_load", "-subtract_pin_load"):
                i += 1
            elif value is None and word.kind == "str" and not opt.startswith("-"):
                value = self._cap(word)
                i += 1
            else:
                objs.extend(self.flatten(word))
                i += 1
        if value is None:
            raise StaError("set_load: missing value")
        for port in self.ports_only(objs, "set_load"):
            self.sdc.loads[port] = value

    def cmd_set_timing_derate(self, args):
        factor = None
        analyses = []
        scopes = []
        # Only cell delays are derated by these rules: nets have no delay and
        # constraint tables are never scaled.
        targets = []
        i = 0
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt == "-early":
                analyses.append(EARLY)
                i += 1
            elif opt == "-late":
                analyses.append(LATE)
                i += 1
            elif opt == "-clock":
                scopes.append("clock")
                i += 1
            elif opt == "-data":
                scopes.append("data")
                i += 1
            elif opt in ("-cell_delay", "-net_delay", "-cell_check", "-static",
                         "-dynamic", "-increment"):
                targets.append(opt)
                i += 1
            elif opt is not None and opt.startswith("-") and not _is_number(opt):
                raise StaError("set_timing_derate: unsupported option %r" % opt)
            elif factor is None and word.kind == "str":
                factor = float(word.as_str())
                i += 1
            else:
                i += 1
        if factor is None:
            raise StaError("set_timing_derate: missing factor")
        if targets and "-cell_delay" not in targets:
            return
        if not analyses:
            analyses = [LATE, EARLY]
        if not scopes:
            scopes = ["clock", "data"]
        for analysis in analyses:
            for scope in scopes:
                self.sdc.derate[(analysis, scope)] = factor

    def _exception(self, args, kind):
        exc = PathException(kind, len(self.sdc.exceptions))
        mult = None
        i = 0
        saw_setup = saw_hold = False
        while i < len(args):
            word = args[i]
            opt = word.text if word.kind == "str" else None
            if opt in ("-from", "-rise_from", "-fall_from"):
                exc.frm = set(self.flatten(args[i + 1]))
                i += 2
            elif opt in ("-to", "-rise_to", "-fall_to"):
                exc.to = set(self.flatten(args[i + 1]))
                i += 2
            elif opt in ("-through", "-rise_through", "-fall_through"):
                exc.through.append(set(self.flatten(args[i + 1])))
                i += 2
            elif opt == "-setup":
                saw_setup = True
                i += 1
            elif opt == "-hold":
                saw_hold = True
                i += 1
            elif opt in ("-start", "-end", "-reset_path", "-comment"):
                i += 2 if opt == "-comment" else 1
            elif opt is not None and opt.startswith("-") and not _is_number(opt):
                raise StaError("%s: unsupported option %r"
                               % ("set_false_path" if kind == "false"
                                  else "set_multicycle_path", opt))
            elif word.kind == "str" and mult is None and kind == "mcp":
                mult = self._int(word)
                i += 1
            else:
                raise StaError("sdc: unexpected argument %r in path exception" % (word,))
        if saw_setup or saw_hold:
            exc.setup = saw_setup
            exc.hold = saw_hold
        if kind == "mcp":
            if mult is None:
                raise StaError("set_multicycle_path: missing multiplier")
            exc.mult = mult
        self.sdc.exceptions.append(exc)

    def cmd_set_multicycle_path(self, args):
        self._exception(args, "mcp")

    def cmd_set_false_path(self, args):
        self._exception(args, "false")


def _is_number(text):
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------
# timing engine
# ---------------------------------------------------------------------------

def frac_gcd(a, b):
    """Greatest common divisor of two positive Fractions, treated exactly."""
    num = math.gcd(a.numerator * b.denominator, b.numerator * a.denominator)
    return Fraction(num, a.denominator * b.denominator)


class CEntry:
    """A clock arrival at one pin, for one (clock, source edge, transition)."""

    __slots__ = ("time", "slew", "src_pin", "src_tr", "src_clock")

    def __init__(self, time, slew, src_pin=None, src_tr=None, src_clock=None):
        self.time = time
        self.slew = slew
        self.src_pin = src_pin
        self.src_tr = src_tr
        self.src_clock = src_clock


class Arr:
    """A data arrival at one pin, for one launch group and transition."""

    __slots__ = ("lt", "ls", "lsrc", "lkey", "llaunch", "et", "es", "esrc", "elaunch")

    def __init__(self):
        self.lt = None            # late arrival
        self.ls = None            # late slew (largest, independent of arrival)
        self.lsrc = None          # (pin, transition) that set the late arrival
        self.lkey = None          # launch key of that source arrival
        self.llaunch = None       # launching clock pin, if any
        self.et = None            # early arrival
        self.es = None            # early slew (smallest)
        self.esrc = None
        self.elaunch = None

    def merge_late(self, time, slew, src, launch, src_key=None):
        if (self.lt is None or time > self.lt
                or (time == self.lt and src is not None
                    and (self.lsrc is None or src < self.lsrc))):
            self.lt = time
            self.lsrc = src
            self.llaunch = launch
            self.lkey = src_key
        self.ls = slew if self.ls is None else max(self.ls, slew)

    def merge_early(self, time, slew, src, launch):
        if (self.et is None or time < self.et
                or (time == self.et and src is not None
                    and (self.esrc is None or src < self.esrc))):
            self.et = time
            self.esrc = src
            self.elaunch = launch
        self.es = slew if self.es is None else min(self.es, slew)


class SetupCheck:
    """One setup check, with everything re-timing needs to redo it."""

    __slots__ = ("slack", "key", "tr", "required", "arc", "clock_slew")

    def __init__(self, slack, key, tr, required, arc, clock_slew):
        self.slack = slack
        self.key = key            # launch group of the checked arrival
        self.tr = tr              # data transition at the endpoint
        self.required = required  # capture side, before the constraint
        self.arc = arc            # constraint arc, or None at an output port
        self.clock_slew = clock_slew


class Endpoint:
    """A timing endpoint: a sequential data pin or a constrained output port."""

    __slots__ = ("name", "setup", "hold", "retimed")

    def __init__(self, name, retimed):
        self.name = name
        self.setup = []           # SetupCheck list
        self.hold = []            # hold slacks
        self.retimed = retimed    # eligible for path-based re-timing

    def setup_slack(self):
        return min((c.slack for c in self.setup), default=None)

    def hold_slack(self):
        return min(self.hold, default=None)

    def worst_setup(self):
        """The check that sets the setup slack; rise wins an exact tie."""
        if not self.setup:
            return None
        return min(self.setup,
                   key=lambda c: (c.slack, 0 if c.tr == RISE else 1, str(c.key)))


class LatchWindow:
    """One latch's transparency window under one of its enable clocks."""

    __slots__ = ("clock", "open_tag", "late", "early", "items")

    def __init__(self, clock, open_tag, late, early):
        self.clock = clock
        self.open_tag = open_tag  # clock edge ('r'/'f') that opens the latch
        self.late = late          # late enable latency at the opening edge
        self.early = early        # early enable latency at the opening edge
        self.items = []           # borrowing D arrivals that also launch Q


class Timing:
    """Graph-based timing analysis over a design with its SDC constraints."""

    def __init__(self, design, sdc):
        self.design = design
        self.sdc = sdc
        self.clk = [REDACTED]             # pin -> {(clock, src_tr, tr): {analysis: CEntry}}
        self.clock_pins = set()
        self.clocks_at = [REDACTED]       # pin -> ordered list of clock names
        self.data = [REDACTED]            # pin -> {launch key: {tr: Arr}}
        self._relation_cache = [REDACTED]
        self._advance = [REDACTED]        # pin -> {(exception index, through index)}
        self.endpoint_checks = [REDACTED]  # endpoint -> list of check records
        self.latch_borrow = [REDACTED]
        self.latch_info = [REDACTED]

    # -- table helpers ----------------------------------------------------
    def _lookup_args(self, in_slew, load):
        return {
            "input_net_transition": in_slew,
            "input_transition_time": in_slew,
            "total_output_net_capacitance": load,
            "output_net_capacitance": load,
        }

    def arc_values(self, arc, out_tr, in_slew, load, analysis, scope):
        """Cell delay (derated) and output slew of one timing arc."""
        dkey = "cell_rise" if out_tr == RISE else "cell_fall"
        skey = "rise_transition" if out_tr == RISE else "fall_transition"
        tbl_d = arc.tables.get(dkey)
        tbl_s = arc.tables.get(skey)
        if tbl_d is None or tbl_s is None:
            raise StaError("timing arc from %s is missing %s/%s tables"
                           % (arc.related_pin, dkey, skey))
        args = self._lookup_args(in_slew, load)
        delay = tbl_d.lookup(args) * self.sdc.derate[(analysis, scope)]
        return delay, tbl_s.lookup(args)

    @staticmethod
    def arc_pairs(arc):
        """(input transition, output transition) pairs an arc propagates."""
        if arc.ttype == "rising_edge":
            return ((RISE, RISE), (RISE, FALL))
        if arc.sense == "positive_unate":
            return ((RISE, RISE), (FALL, FALL))
        if arc.sense == "negative_unate":
            return ((RISE, FALL), (FALL, RISE))
        return ((RISE, RISE), (RISE, FALL), (FALL, RISE), (FALL, FALL))

    def constraint_value(self, arc, tr, data_slew, clock_slew):
        key = "rise_constraint" if tr == RISE else "fall_constraint"
        tbl = arc.tables.get(key)
        if tbl is None:
            other = "fall_constraint" if tr == RISE else "rise_constraint"
            tbl = arc.tables.get(other)
        if tbl is None:
            raise StaError("check arc from %s has no constraint table" % arc.related_pin)
        return tbl.lookup({
            "constrained_pin_transition": data_slew,
            "related_pin_transition": clock_slew,
        })

    def check_arc(self, inst, kinds):
        """The first timing group on the data pin whose timing_type is in kinds."""
        cell = inst.cell
        pdef = cell.pin(cell.data_pin)
        for arc in pdef.timings:
            if arc.ttype in kinds and arc.related_pin == cell.clock_pin:
                return arc
        return None

    def seq_out_arcs(self, inst):
        """(output pin id, arc) for every clock-to-output arc of a sequential cell."""
        out = []
        cell = inst.cell
        for pname in sorted(inst.conns):
            pdef = cell.pins[pname]
            if pdef.direction != "output":
                continue
            for arc in pdef.timings:
                if arc.ttype == "rising_edge" and arc.related_pin == cell.clock_pin:
                    out.append(("%s/%s" % (inst.name, pname), arc))
        return out

    def comb_out_arcs(self, inst, from_pin):
        """Combinational arcs of `inst` driven by `from_pin`."""
        out = []
        cell = inst.cell
        for pname in sorted(inst.conns):
            pdef = cell.pins[pname]
            if pdef.direction != "output":
                continue
            for arc in pdef.timings:
                if arc.ttype == "combinational" and arc.related_pin == from_pin:
                    out.append(("%s/%s" % (inst.name, pname), arc))
        return out

    # -- clock network ----------------------------------------------------
    def analyse_clocks(self):
        sdc = self.sdc
        primaries = [c for c in sdc.clocks.values() if c.generated is None]
        generated = [c for c in sdc.clocks.values() if c.generated is not None]
        for clk in primaries:
            self._propagate_clock(clk)
        pending = list(generated)
        while pending:
            progress = False
            for clk in list(pending):
                master = self._find_master(clk)
                if master is None:
                    continue
                self._derive_waveform(clk, master)
                self._propagate_clock(clk)
                pending.remove(clk)
                progress = True
            if not progress:
                names = ", ".join(c.name for c in pending)
                raise StaError("generated clock(s) %s have no master clock" % names)
        for pid, entries in self.clk.items():
            names = []
            for (cname, _src, _tr) in entries:
                if cname not in names:
                    names.append(cname)
            self.clocks_at[pid] = names

    def _find_master(self, clk):
        spec = clk.generated
        want = spec.master_name
        found = []
        for key in self.clk.get(spec.source_pin, ()):
            cname = key[0]
            master = self.sdc.clocks[cname]
            if master.period is None:
                continue
            if want is not None and cname != want:
                continue
            if cname not in [c.name for c in found]:
                found.append(master)
        if not found:
            return None
        return min(found, key=lambda c: c.name)

    def _derive_waveform(self, clk, master):
        spec = clk.generated
        clk.master = master
        P, r, f = master.period, master.rise, master.fall
        if spec.mode == "multiply_by":
            k = spec.value
            clk.period = P / k
            clk.rise = r
            clk.fall = r + (f - r) / k
        else:
            if spec.mode == "divide_by":
                n = spec.value
                edges = [1, n + 1, 2 * n + 1]
            else:
                edges = spec.edges

            def edge_time(e):
                step = (e - 1) // 2
                return (r if e % 2 == 1 else f) + step * P

            e1, e2, e3 = (edge_time(e) for e in edges)
            clk.rise = e1
            clk.fall = e2
            clk.period = e3 - e1
        if clk.period is None or clk.period <= 0:
            raise StaError("generated clock %s has a non-positive period" % clk.name)

    def _clock_network_load(self, pid):
        """True if a load pin reached from the clock network belongs to it."""
        node = self.design.pins.get(pid)
        if node is None or node.kind != "cell_in":
            return False
        cell = node.inst.cell
        if cell.is_sequential:
            return node.pname == cell.clock_pin
        return True

    def _propagate_clock(self, clk):
        design = self.design
        seeds = [REDACTED]
        if clk.generated is None:
            slews = self.sdc.input_transition
            for pid in clk.sources:
                slew = slews.get(pid, 0.0)
                for tr in TRANSITIONS:
                    seeds.setdefault(pid, [REDACTED])[(tr, tr)] = {
                        LATE: CEntry(0.0, slew),
                        EARLY: CEntry(0.0, slew),
                    }
        else:
            for pid in clk.sources:
                seeds[pid] = self._generated_seed(clk, pid)

        for pid, keys in seeds.items():
            dest = self.clk.setdefault(pid, [REDACTED])
            for (srctr, tr), entries in keys.items():
                dest[(clk.name, srctr, tr)] = entries
            self.clock_pins.add(pid)

        reached = set(seeds)
        for pid in design.order:
            if pid not in reached:
                continue
            node = design.pins[pid]
            keys = [k for k in self.clk.get(pid, ()) if k[0] == clk.name]
            if not keys:
                continue
            if node.is_driver:
                for load in design.net_loads.get(node.net, ()):
                    if not self._clock_network_load(load):
                        continue
                    self.clock_pins.add(load)
                    reached.add(load)
                    dest = self.clk.setdefault(load, [REDACTED])
                    for key in keys:
                        src = self.clk[pid][key]
                        for analysis in (LATE, EARLY):
                            entry = src[analysis]
                            self._merge_clock(dest, key, analysis, entry.time,
                                              entry.slew, pid, key[2], None)
            if node.kind == "cell_in":
                for out_pid, arc in self.comb_out_arcs(node.inst, node.pname):
                    out_node = design.pins.get(out_pid)
                    if out_node is None:
                        continue
                    self.clock_pins.add(out_pid)
                    reached.add(out_pid)
                    dest = self.clk.setdefault(out_pid, [REDACTED])
                    for key in keys:
                        _cname, srctr, in_tr = key
                        for pair_in, pair_out in self.arc_pairs(arc):
                            if pair_in != in_tr:
                                continue
                            for analysis in (LATE, EARLY):
                                entry = self.clk[pid][key][analysis]
                                delay, slew = self.arc_values(
                                    arc, pair_out, entry.slew, out_node.load_cap,
                                    analysis, "clock")
                                self._merge_clock(dest, (clk.name, srctr, pair_out),
                                                  analysis, entry.time + delay, slew,
                                                  pid, in_tr, None)

    def _generated_seed(self, clk, pid):
        """Clock arrivals at the register output a generated clock is defined on."""
        design = self.design
        node = design.pin(pid)
        master = clk.master
        if node.inst is None or not node.inst.cell.is_sequential:
            # Defined on a pin the master already reaches: the generated clock
            # simply inherits the master's arrival there.
            out = [REDACTED]
            for tr in TRANSITIONS:
                base = self.clock_latency(pid, master, tr, LATE)
                early = self.clock_latency(pid, master, tr, EARLY)
                if base is None or early is None:
                    raise StaError("generated clock %s is not defined on a pin the "
                                   "master clock reaches" % clk.name)
                out[(tr, tr)] = {
                    LATE: CEntry(base[0], base[1], pid, tr, master.name),
                    EARLY: CEntry(early[0], early[1], pid, tr, master.name),
                }
            return out
        inst = node.inst
        ck_local = inst.cell.clock_pin
        if ck_local not in inst.conns:
            raise StaError("register %s has no clock connection" % inst.name)
        ck_pid = "%s/%s" % (inst.name, ck_local)
        arc = None
        for out_pid, cand in self.seq_out_arcs(inst):
            if out_pid == pid:
                arc = cand
                break
        if arc is None:
            raise StaError("no clock-to-output arc for generated clock %s" % clk.name)
        out = [REDACTED]
        for tr in TRANSITIONS:
            entries = [REDACTED]
            for analysis in (LATE, EARLY):
                base = self.clock_latency(ck_pid, master, RISE, analysis)
                if base is None:
                    raise StaError("master clock %s does not reach %s"
                                   % (master.name, ck_pid))
                time, slew, _srctr = base
                delay, out_slew = self.arc_values(arc, tr, slew, node.load_cap,
                                                  analysis, "clock")
                entries[analysis] = CEntry(time + delay, out_slew,
                                           ck_pid, RISE, master.name)
            out[(tr, tr)] = entries
        return out

    @staticmethod
    def _merge_clock(dest, key, analysis, time, slew, src_pin, src_tr, src_clock):
        slot = dest.setdefault(key, [REDACTED])
        cur = slot.get(analysis)
        if cur is None:
            slot[analysis] = CEntry(time, slew, src_pin, src_tr, src_clock)
            return
        better = time > cur.time if analysis == LATE else time < cur.time
        tie = (time == cur.time and src_pin is not None
               and (cur.src_pin is None
                    or (src_pin, src_tr) < (cur.src_pin, cur.src_tr)))
        if better or tie:
            cur.time = time
            cur.src_pin = src_pin
            cur.src_tr = src_tr
            cur.src_clock = src_clock
        cur.slew = max(cur.slew, slew) if analysis == LATE else min(cur.slew, slew)

    def clock_key(self, pid, clock_name, tr):
        """Pick the (clock, source edge, transition) key to use at a pin."""
        keys = [k for k in self.clk.get(pid, ()) if k[0] == clock_name and k[2] == tr]
        return min(keys) if keys else None

    def clock_latency(self, pid, clock, tr, analysis):
        """(latency, slew, source edge) of `clock` at `pid`, or None."""
        key = self.clock_key(pid, clock.name, tr)
        if key is None:
            return None
        entry = self.clk[pid][key][analysis]
        if not clock.propagated:
            return 0.0, clock.transition, key[1]
        return entry.time, entry.slew, key[1]

    def edge_tag(self, pid, clock, tr):
        """Which clock edge ('r'/'f') produces transition `tr` at a clock pin."""
        key = self.clock_key(pid, clock.name, tr)
        if key is None:
            return None
        return "r" if key[1] == RISE else "f"

    # -- clock path tracing (for CPPR) ------------------------------------
    def clock_path(self, pid, tr, clock_name, analysis):
        """Chain of (pin, transition, clock, source edge) back to the clock source."""
        path = []
        seen = set()
        cur_pid, cur_tr, cur_clock = pid, tr, clock_name
        key = self.clock_key(cur_pid, cur_clock, cur_tr)
        while key is not None:
            if (cur_pid, cur_tr, cur_clock) in seen:
                break
            seen.add((cur_pid, cur_tr, cur_clock))
            path.append((cur_pid, cur_tr, cur_clock, key[1]))
            entry = self.clk[cur_pid][key][analysis]
            if entry.src_pin is None:
                break
            cur_pid = entry.src_pin
            cur_tr = entry.src_tr
            if entry.src_clock is not None:
                cur_clock = entry.src_clock
            key = self.clock_key(cur_pid, cur_clock, cur_tr)
        return path

    def cppr_credit(self, launch_pin, launch_clock, launch_analysis,
                    capture_pin, capture_tr, capture_clock, capture_analysis):
        """Common path pessimism credit between a launch and a capture path."""
        if launch_pin is None or capture_pin is None:
            return 0.0
        if launch_clock is None or capture_clock is None:
            return 0.0
        if not (launch_clock.propagated and capture_clock.propagated):
            return 0.0
        lpath = self.clock_path(launch_pin, RISE, launch_clock.name, launch_analysis)
        cpath = self.clock_path(capture_pin, capture_tr, capture_clock.name,
                                capture_analysis)
        cmap = [REDACTED]
        for cpid, ctr, _cclk, _csrc in cpath:
            cmap.setdefault(cpid, ctr)
        for lpid, ltr, lclk, lsrc in lpath:
            if lpid not in cmap:
                continue
            if cmap[lpid] != ltr:
                return 0.0
            entries = self.clk[lpid].get((lclk, lsrc, ltr))
            if entries is None or not self.sdc.clocks[lclk].propagated:
                return 0.0
            return entries[LATE].time - entries[EARLY].time
        return 0.0

    # -- clock edge relationships -----------------------------------------
    def setup_relation(self, lclk, ltag, cclk, ctag):
        """Nearest capture edge strictly after a launch edge, minimised over
        every launch edge of the common period.

        Over the common period the launch edges fall at `le + k * Pl`, so the
        distances to the following capture edge are exactly the positive values
        of `(ce - le) mod g` shifted by multiples of `g = gcd(Pl, Pc)`; the
        smallest of them is that remainder, or `g` when it vanishes.
        """
        cache_key = (lclk.name, ltag, cclk.name, ctag)
        hit = self._relation_cache.get(cache_key)
        if hit is not None:
            return hit
        step = frac_gcd(lclk.period, cclk.period)
        rel = (cclk.edge(ctag) - lclk.edge(ltag)) % step
        if rel == 0:
            rel = step
        self._relation_cache[cache_key] = rel
        return rel

    # -- path exceptions --------------------------------------------------
    def prepare_exceptions(self):
        design = self.design
        for idx, exc in enumerate(self.sdc.exceptions):
            for ti, objs in enumerate(exc.through):
                for kind, name in objs:
                    if kind in ("pin", "port"):
                        pins = [name]
                    elif kind == "cell":
                        inst = design.netlist.instances[name]
                        pins = ["%s/%s" % (name, p) for p in inst.conns]
                    else:
                        raise StaError("-through on %s objects is not supported" % kind)
                    for pid in pins:
                        self._advance.setdefault(pid, set()).add((idx, ti))

    def init_state(self, launch_tags):
        state = []
        for exc in self.sdc.exceptions:
            if exc.frm is None or (exc.frm & launch_tags):
                state.append(0)
            else:
                state.append(-1)
        return tuple(state)

    def advance_state(self, state, pid):
        adv = self._advance.get(pid)
        if not adv:
            return state
        out = list(state)
        changed = False
        for idx, ti in adv:
            if out[idx] == ti:
                out[idx] = ti + 1
                changed = True
        return tuple(out) if changed else state

    def endpoint_exceptions(self, state, tags):
        """(false setup, false hold, setup multiplier, hold multiplier)."""
        false_setup = false_hold = False
        best_setup = best_hold = None
        for idx, exc in enumerate(self.sdc.exceptions):
            if state[idx] != len(exc.through):
                continue
            if exc.to is not None and not (exc.to & tags):
                continue
            if exc.kind == "false":
                false_setup = false_setup or exc.setup
                false_hold = false_hold or exc.hold
            else:
                if exc.setup and (best_setup is None
                                  or exc.specificity > best_setup.specificity):
                    best_setup = exc
                if exc.hold and (best_hold is None
                                 or exc.specificity > best_hold.specificity):
                    best_hold = exc
        return (false_setup, false_hold,
                best_setup.mult if best_setup else 1,
                best_hold.mult if best_hold else 0)

    # -- data propagation -------------------------------------------------
    def analyse_data(self):
        design = self.design
        self.prepare_exceptions()
        latch_done = set()
        for pid in design.order:
            if pid in self.clock_pins:
                continue
            node = design.pins[pid]
            if node.kind == "in_port":
                self._seed_port(pid)
            elif node.kind in ("cell_in", "out_port"):
                self._copy_from_driver(pid, node)
            elif node.kind == "cell_out":
                cell = node.inst.cell
                if cell.seq_kind == "ff":
                    self._launch_ff(pid, node)
                elif cell.seq_kind == "latch":
                    if node.inst.name not in latch_done:
                        self._latch_checks(node.inst)
                        latch_done.add(node.inst.name)
                    self._launch_latch(pid, node)
                else:
                    self._eval_comb_out(pid, node)
        for inst in design.seq_instances():
            if inst.cell.seq_kind == "latch" and inst.name not in latch_done:
                self._latch_checks(inst)
                latch_done.add(inst.name)
        self._register_checks()
        self._output_checks()

    def _slot(self, pid, key, tr):
        trmap = self.data.setdefault(pid, [REDACTED]).setdefault(key, [REDACTED])
        arr = trmap.get(tr)
        if arr is None:
            arr = Arr()
            trmap[tr] = arr
        return arr

    def _seed_port(self, pid):
        delays = self.sdc.input_delays.get(pid)
        if not delays:
            return
        slew = self.sdc.input_transition.get(pid, 0.0)
        for cname in sorted(delays):
            iod = delays[cname]
            tags = {("port", pid), ("pin", pid), ("clock", cname)}
            key = (cname, "r", self.advance_state(self.init_state(tags), pid))
            for tr in TRANSITIONS:
                arr = self._slot(pid, key, tr)
                arr.merge_late(iod.late(), slew, None, None)
                arr.merge_early(iod.early(), slew, None, None)

    def _copy_from_driver(self, pid, node):
        drv = self.design.net_driver.get(node.net)
        if drv is None or drv in self.clock_pins:
            return
        src = self.data.get(drv)
        if not src:
            return
        for key, trmap in src.items():
            nkey = (key[0], key[1], self.advance_state(key[2], pid))
            for tr, arr in trmap.items():
                dest = self._slot(pid, nkey, tr)
                if arr.lt is not None:
                    dest.merge_late(arr.lt, arr.ls, (drv, tr), arr.llaunch, key)
                if arr.et is not None:
                    dest.merge_early(arr.et, arr.es, (drv, tr), arr.elaunch)

    def _eval_comb_out(self, pid, node):
        load = node.load_cap
        for src_pid, arc in node.fanin:
            if arc.ttype != "combinational":
                continue
            src = self.data.get(src_pid)
            if not src:
                continue
            pairs = self.arc_pairs(arc)
            for key, trmap in src.items():
                nkey = (key[0], key[1], self.advance_state(key[2], pid))
                for in_tr, arr in trmap.items():
                    for pair_in, out_tr in pairs:
                        if pair_in != in_tr:
                            continue
                        dest = self._slot(pid, nkey, out_tr)
                        if arr.lt is not None:
                            delay, slew = self.arc_values(arc, out_tr, arr.ls, load,
                                                          LATE, "data")
                            dest.merge_late(arr.lt + delay, slew, (src_pid, in_tr),
                                            arr.llaunch, key)
                        if arr.et is not None:
                            delay, slew = self.arc_values(arc, out_tr, arr.es, load,
                                                          EARLY, "data")
                            dest.merge_early(arr.et + delay, slew, (src_pid, in_tr),
                                             arr.elaunch)

    def _launch_ff(self, pid, node):
        inst = node.inst
        ck_local = inst.cell.clock_pin
        if ck_local not in inst.conns:
            return
        ck_pid = "%s/%s" % (inst.name, ck_local)
        arc = None
        for out_pid, cand in self.seq_out_arcs(inst):
            if out_pid == pid:
                arc = cand
                break
        if arc is None:
            return
        for cname in self.clocks_at.get(ck_pid, ()):
            clk = self.sdc.clocks[cname]
            late = self.clock_latency(ck_pid, clk, RISE, LATE)
            early = self.clock_latency(ck_pid, clk, RISE, EARLY)
            tag = self.edge_tag(ck_pid, clk, RISE)
            if late is None or early is None or tag is None:
                continue
            tags = {("cell", inst.name), ("pin", pid), ("pin", ck_pid),
                    ("clock", cname)}
            key = (cname, tag, self.advance_state(self.init_state(tags), pid))
            for out_tr in TRANSITIONS:
                dest = self._slot(pid, key, out_tr)
                delay, slew = self.arc_values(arc, out_tr, late[1], node.load_cap,
                                              LATE, "data")
                dest.merge_late(late[0] + delay, slew, None, ck_pid)
                delay, slew = self.arc_values(arc, out_tr, early[1], node.load_cap,
                                              EARLY, "data")
                dest.merge_early(early[0] + delay, slew, None, ck_pid)

    # -- checks -----------------------------------------------------------
    def _endpoint(self, name, retimed=False):
        rec = self.endpoint_checks.get(name)
        if rec is None:
            rec = Endpoint(name, retimed)
            self.endpoint_checks[name] = rec
        rec.retimed = rec.retimed or retimed
        return rec

    def _register_checks(self):
        for inst in self.design.seq_instances():
            cell = inst.cell
            if cell.seq_kind != "ff":
                continue
            d_pid = "%s/%s" % (inst.name, cell.data_pin)
            rec = self._endpoint(d_pid, retimed=True)
            ck_local = cell.clock_pin
            if ck_local not in inst.conns or cell.data_pin not in inst.conns:
                continue
            ck_pid = "%s/%s" % (inst.name, ck_local)
            setup_arc = self.check_arc(inst, ("setup_rising", "setup_falling"))
            hold_arc = self.check_arc(inst, ("hold_rising", "hold_falling"))
            arrivals = self.data.get(d_pid, [REDACTED])
            for cname in self.clocks_at.get(ck_pid, ()):
                cclk = self.sdc.clocks[cname]
                ctag = self.edge_tag(ck_pid, cclk, RISE)
                cap_late = self.clock_latency(ck_pid, cclk, RISE, LATE)
                cap_early = self.clock_latency(ck_pid, cclk, RISE, EARLY)
                if ctag is None or cap_late is None or cap_early is None:
                    continue
                tags = {("cell", inst.name), ("pin", d_pid), ("pin", ck_pid),
                        ("clock", cname)}
                for key, trmap in arrivals.items():
                    lclk = self.sdc.clocks[key[0]]
                    f_setup, f_hold, m_setup, m_hold = self.endpoint_exceptions(
                        key[2], tags)
                    base = self.setup_relation(lclk, key[1], cclk, ctag)
                    setup_rel = float(base + (m_setup - 1) * cclk.period)
                    hold_rel = float(base + (m_setup - 1) * cclk.period
                                     - min(lclk.period, cclk.period)
                                     - m_hold * lclk.period)
                    for tr, arr in trmap.items():
                        if not f_setup and arr.lt is not None and setup_arc is not None:
                            credit = self.cppr_credit(arr.llaunch, lclk, LATE,
                                                      ck_pid, RISE, cclk, EARLY)
                            required = setup_rel + cap_early[0] + credit
                            constraint = self.constraint_value(
                                setup_arc, tr, arr.ls, cap_early[1])
                            rec.setup.append(SetupCheck(
                                required - constraint - arr.lt, key, tr,
                                required, setup_arc, cap_early[1]))
                        if not f_hold and arr.et is not None and hold_arc is not None:
                            credit = self.cppr_credit(arr.elaunch, lclk, EARLY,
                                                      ck_pid, RISE, cclk, LATE)
                            constraint = self.constraint_value(
                                hold_arc, tr, arr.es, cap_late[1])
                            required = hold_rel + cap_late[0] + constraint
                            rec.hold.append(arr.et - required + credit)

    def _output_checks(self):
        for port, delays in self.sdc.output_delays.items():
            rec = self._endpoint(port, retimed=True)
            arrivals = self.data.get(port, [REDACTED])
            for cname in sorted(delays):
                iod = delays[cname]
                cclk = self.sdc.clocks[cname]
                tags = {("port", port), ("pin", port), ("clock", cname)}
                for key, trmap in arrivals.items():
                    lclk = self.sdc.clocks[key[0]]
                    f_setup, f_hold, m_setup, m_hold = self.endpoint_exceptions(
                        key[2], tags)
                    base = self.setup_relation(lclk, key[1], cclk, "r")
                    setup_rel = float(base + (m_setup - 1) * cclk.period)
                    hold_rel = float(base + (m_setup - 1) * cclk.period
                                     - min(lclk.period, cclk.period)
                                     - m_hold * lclk.period)
                    for tr, arr in trmap.items():
                        if not f_setup and arr.lt is not None and iod.late() is not None:
                            required = setup_rel - iod.late()
                            rec.setup.append(SetupCheck(
                                required - arr.lt, key, tr, required, None, 0.0))
                        if not f_hold and arr.et is not None and iod.early() is not None:
                            rec.hold.append(arr.et - (hold_rel + iod.early()))

    # -- latches ----------------------------------------------------------
    def _latch_checks(self, inst):
        """Setup, hold and borrow for a latch, plus its Q launch data."""
        cell = inst.cell
        g_local, d_local = cell.clock_pin, cell.data_pin
        d_pid = "%s/%s" % (inst.name, d_local)
        rec = self._endpoint(d_pid)
        self.latch_borrow.setdefault(d_pid, None)
        self.latch_info[inst.name] = []
        if g_local not in inst.conns or d_local not in inst.conns:
            return
        g_pid = "%s/%s" % (inst.name, g_local)
        setup_arc = self.check_arc(inst, ("setup_falling", "setup_rising"))
        hold_arc = self.check_arc(inst, ("hold_falling", "hold_rising"))
        arrivals = self.data.get(d_pid, [REDACTED])
        tags = {("cell", inst.name), ("pin", d_pid), ("pin", g_pid)}
        best_borrow = None
        for cname in self.clocks_at.get(g_pid, ()):
            lat = self.sdc.clocks[cname]
            open_tag = self.edge_tag(g_pid, lat, RISE)
            close_tag = self.edge_tag(g_pid, lat, FALL)
            open_early = self.clock_latency(g_pid, lat, RISE, EARLY)
            close_early = self.clock_latency(g_pid, lat, FALL, EARLY)
            open_late = self.clock_latency(g_pid, lat, RISE, LATE)
            close_late = self.clock_latency(g_pid, lat, FALL, LATE)
            if None in (open_tag, close_tag, open_early, close_early, open_late,
                        close_late):
                continue
            window = lat.edge(close_tag) - lat.edge(open_tag)
            if window <= 0:
                window += lat.period
            ctags = tags | {("clock", cname)}
            window_info = LatchWindow(cname, open_tag, open_late, open_early)
            for key, trmap in arrivals.items():
                lclk = self.sdc.clocks[key[0]]
                f_setup, f_hold, m_setup, m_hold = self.endpoint_exceptions(
                    key[2], ctags)
                open_rel = float(self.setup_relation(lclk, key[1], lat, open_tag)
                                 + (m_setup - 1) * lat.period)
                close_base = self.setup_relation(lclk, key[1], lat, close_tag)
                hold_rel = float(close_base + (m_setup - 1) * lat.period
                                 - min(lclk.period, lat.period)
                                 - m_hold * lclk.period)
                for tr, arr in trmap.items():
                    if arr.lt is not None and setup_arc is not None:
                        credit = self.cppr_credit(arr.llaunch, lclk, LATE,
                                                  g_pid, RISE, lat, EARLY)
                        constraint = self.constraint_value(setup_arc, tr, arr.ls,
                                                           close_early[1])
                        limit = max(0.0, float(window) + close_early[0]
                                    - open_early[0] - constraint)
                        open_time = open_rel + open_early[0] + credit
                        borrow = min(max(arr.lt - open_time, 0.0), limit)
                        if not f_setup:
                            rec.setup.append(SetupCheck(
                                open_time + borrow - arr.lt, key, tr,
                                open_time + borrow, None, close_early[1]))
                            if best_borrow is None or borrow > best_borrow:
                                best_borrow = borrow
                        if borrow > 0.0:
                            window_info.items.append((tr, open_rel, arr.lt, arr.ls))
                    if not f_hold and arr.et is not None and hold_arc is not None:
                        credit = self.cppr_credit(arr.elaunch, lclk, EARLY,
                                                  g_pid, FALL, lat, LATE)
                        constraint = self.constraint_value(hold_arc, tr, arr.es,
                                                           close_late[1])
                        required = hold_rel + close_late[0] + constraint
                        rec.hold.append(arr.et - required + credit)
            self.latch_info[inst.name].append(window_info)
        self.latch_borrow[d_pid] = best_borrow

    def _launch_latch(self, pid, node):
        """Arrivals on a latch output: the enable launch plus borrowed paths."""
        inst = node.inst
        cell = inst.cell
        g_local, d_local = cell.clock_pin, cell.data_pin
        g_pid = "%s/%s" % (inst.name, g_local)
        d_pid = "%s/%s" % (inst.name, d_local)
        enable_arc = None
        for out_pid, cand in self.seq_out_arcs(inst):
            if out_pid == pid:
                enable_arc = cand
                break
        dq_arc = None
        for src_pid, arc in node.fanin:
            if src_pid == d_pid and arc.ttype == "combinational":
                dq_arc = arc
                break
        for info in self.latch_info.get(inst.name, ()):
            tags = {("cell", inst.name), ("pin", pid), ("pin", g_pid),
                    ("clock", info.clock)}
            key = (info.clock, info.open_tag,
                   self.advance_state(self.init_state(tags), pid))
            if enable_arc is not None:
                for out_tr in TRANSITIONS:
                    dest = self._slot(pid, key, out_tr)
                    delay, slew = self.arc_values(enable_arc, out_tr, info.late[1],
                                                  node.load_cap, LATE, "data")
                    dest.merge_late(info.late[0] + delay, slew, None, g_pid)
                    delay, slew = self.arc_values(enable_arc, out_tr, info.early[1],
                                                  node.load_cap, EARLY, "data")
                    dest.merge_early(info.early[0] + delay, slew, None, g_pid)
            if dq_arc is None:
                continue
            pairs = self.arc_pairs(dq_arc)
            for tr, open_rel, d_late, d_slew in info.items:
                for pair_in, out_tr in pairs:
                    if pair_in != tr:
                        continue
                    delay, slew = self.arc_values(dq_arc, out_tr, d_slew,
                                                  node.load_cap, LATE, "data")
                    dest = self._slot(pid, key, out_tr)
                    # A latch output is a path start point: no back-trace through D.
                    dest.merge_late(d_late - open_rel + delay, slew, None, g_pid)

    # -- path-based re-timing ---------------------------------------------
    def path_based(self, limit=5):
        """Re-time the `limit` endpoints with the smallest setup slack."""
        cands = []
        for name, rec in self.endpoint_checks.items():
            best = rec.worst_setup()
            if rec.retimed and best is not None:
                cands.append((best.slack, name, best))
        cands.sort(key=lambda item: (item[0], item[1]))
        return {name: self._retime(name, best) for _slack, name, best in cands[:limit]}

    def _retime(self, endpoint, check):
        """Re-evaluate one worst path with the slews it carries itself."""
        design = self.design
        chain = []                # [(pin, transition, Arr)], endpoint first
        pid, tr, key = endpoint, check.tr, check.key
        seen = set()
        while True:
            arr = self.data[pid][key][tr]
            chain.append((pid, tr, arr))
            if arr.lsrc is None or (pid, tr, key) in seen:
                break
            seen.add((pid, tr, key))
            nxt_pid, nxt_tr = arr.lsrc
            nxt_key = arr.lkey if arr.lkey is not None else key
            nxt = self.data.get(nxt_pid, [REDACTED]).get(nxt_key, [REDACTED]).get(nxt_tr)
            if nxt is None or nxt.lt is None:
                break
            pid, tr, key = nxt_pid, nxt_tr, nxt_key
        chain.reverse()

        time, slew = chain[0][2].lt, chain[0][2].ls
        for idx in range(1, len(chain)):
            prev_pid, prev_tr, _prev = chain[idx - 1]
            cur_pid, cur_tr, _cur = chain[idx]
            cur = design.pins[cur_pid]
            prev = design.pins[prev_pid]
            if cur.kind == "cell_out" and prev.inst is cur.inst:
                arc = self._find_arc(cur, prev_pid, prev_tr, cur_tr)
                if arc is None:
                    continue
                delay, slew = self.arc_values(arc, cur_tr, slew, cur.load_cap,
                                              LATE, "data")
                time += delay
        constraint = 0.0
        if check.arc is not None:
            constraint = self.constraint_value(check.arc, check.tr, slew,
                                               check.clock_slew)
        return check.required - constraint - time

    def _find_arc(self, node, src_pid, in_tr, out_tr):
        for cand_src, arc in node.fanin:
            if cand_src != src_pid:
                continue
            if (in_tr, out_tr) in self.arc_pairs(arc):
                return arc
        return None


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def build_report(timing):
    endpoints = [REDACTED]
    for name in sorted(timing.endpoint_checks):
        rec = timing.endpoint_checks[name]
        endpoints[name] = {"setup": rec.setup_slack(), "hold": rec.hold_slack()}

    def summarise(kind):
        slacks = [v[kind] for v in endpoints.values() if v[kind] is not None]
        if not slacks:
            return None, 0.0
        return min(slacks), float(sum(s for s in slacks if s < 0.0))

    wns_setup, tns_setup = summarise("setup")
    wns_hold, tns_hold = summarise("hold")

    arrivals = [REDACTED]
    for pid in sorted(timing.data):
        if pid in timing.clock_pins:
            continue
        # Merge the launch groups: largest late and smallest early arrival.
        groups = timing.data[pid].values()
        out = [REDACTED]
        for name, attr, pick in (("late", "lt", max), ("early", "et", min)):
            for tr in (RISE, FALL):
                values = []
                for group in groups:
                    arr = group.get(tr)
                    if arr is not None and getattr(arr, attr) is not None:
                        values.append(getattr(arr, attr))
                out["%s_%s" % (name, tr)] = pick(values) if values else None
        if any(value is not None for value in out.values()):
            arrivals[pid] = out

    borrow = {name: timing.latch_borrow[name] for name in sorted(timing.latch_borrow)}
    pba = timing.path_based()
    return {
        "wns_setup": wns_setup,
        "tns_setup": tns_setup,
        "wns_hold": wns_hold,
        "tns_hold": tns_hold,
        "endpoints": endpoints,
        "arrivals": arrivals,
        "borrow": borrow,
        "pba_setup": {name: pba[name] for name in sorted(pba)},
    }


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def analyse(lib_path, netlist_path, sdc_path):
    lib = parse_liberty(lib_path)
    netlist = parse_verilog(netlist_path, lib)
    design = Design(lib, netlist)
    sdc = Sdc()
    sdc.cap_scale = 1.0 / lib.cap_scale          # SDC default capacitance is pF
    interp = SdcInterp(design, sdc)
    interp.run(parse_sdc(sdc_path))
    design.add_port_loads(sdc.loads)
    timing = Timing(design, sdc)
    timing.analyse_clocks()
    timing.analyse_data()
    return build_report(timing)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Static timing analysis for a Liberty NLDM / SDC 2.1 subset")
    parser.add_argument("--lib", required=True, help="Liberty library file")
    parser.add_argument("--netlist", required=True, help="structural Verilog netlist")
    parser.add_argument("--sdc", required=True, help="SDC constraints")
    parser.add_argument("--out", required=True, help="JSON report to write")
    args = parser.parse_args(argv)

    try:
        report = analyse(args.lib, args.netlist, args.sdc)
    except StaError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except (LookupError, ValueError, TypeError, ArithmeticError,
            AttributeError, RecursionError, OSError) as exc:
        # Anything the explicit checks missed is still an unusable input: the
        # report must not be written, so report it the same way.
        print("error: malformed input (%s: %s)" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 2
    try:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=1, allow_nan=False)
            fh.write("\n")
    except OSError as exc:
        print("error: cannot write report: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
