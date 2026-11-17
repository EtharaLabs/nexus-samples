"""Every way to take exactly one element away from a finding, and nothing else.

A database loses one row; one column, with its values and the indexes on it; one
table, with its indexes; or one index. A statement, or any subquery inside it, loses
one item of a select list that has several; one AND-conjunct of a WHERE or an ON, or
the whole WHERE when it is one conjunct; one join, with its ON; one ORDER BY key, or
the whole ORDER BY when it has one key; or its LIMIT. Parentheses only group, so the
conjuncts of (a AND b) AND c are a, b and c.

Statements are cut on the engine's own tokens and the kept text is copied verbatim,
so every variant is the finding's statement with one span removed.
"""

import copy

from tarn import lex


def _same(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def database_reductions(db: dict) -> list:
    out = []
    tables = db.get("tables", {})
    for tname, tdef in tables.items():
        for r in range(len(tdef.get("rows", []))):
            d = copy.deepcopy(db)
            del d["tables"][tname]["rows"][r]
            out.append((f"row {r} of {tname}", d))
        columns = tdef.get("columns", [])
        if len(columns) > 1:
            for c, col in enumerate(columns):
                d = copy.deepcopy(db)
                t = d["tables"][tname]
                del t["columns"][c]
                if "rows" in t:
                    t["rows"] = [row[:c] + row[c + 1 :] for row in t["rows"]]
                if "indexes" in d:
                    d["indexes"] = [
                        ix
                        for ix in d["indexes"]
                        if not (
                            _same(ix.get("table"), tname)
                            and _same(ix.get("column"), col.get("name"))
                        )
                    ]
                out.append((f"column {col.get('name')} of {tname}", d))
    if len(tables) > 1:
        for tname in tables:
            d = copy.deepcopy(db)
            del d["tables"][tname]
            if "indexes" in d:
                d["indexes"] = [
                    ix for ix in d["indexes"] if not _same(ix.get("table"), tname)
                ]
            out.append((f"table {tname}", d))
    for i, ix in enumerate(db.get("indexes", []) or []):
        d = copy.deepcopy(db)
        del d["indexes"][i]
        out.append((f"index {ix.get('name')}", d))
    return out


class _Cutter:
    def __init__(self, sql: str):
        self.sql = sql
        self.toks = lex.tokenize(sql)
        self.match = {}
        stack = []
        for i, t in enumerate(self.toks):
            if t.kind == "punct" and t.text == "(":
                stack.append(i)
            elif t.kind == "punct" and t.text == ")" and stack:
                self.match[stack.pop()] = i
        self.cuts = []

    def kw(self, i: int, word: str) -> bool:
        return self.toks[i].kind == "kw" and self.toks[i].text == word

    def punct(self, i: int, text: str) -> bool:
        return self.toks[i].kind == "punct" and self.toks[i].text == text

    def text_without(self, a: int, b: int) -> str:
        start, end = self.toks[a].pos, self.toks[b].pos
        return (self.sql[:start].rstrip() + " " + self.sql[end:].lstrip()).strip()

    def top(self, a: int, b: int):
        """Indices in [a, b) at paren depth 0 and outside any CASE ... END."""
        i, case = a, 0
        while i < b:
            if self.punct(i, "(") and i in self.match:
                i = self.match[i] + 1
                continue
            if self.kw(i, "case"):
                case += 1
            elif self.kw(i, "end") and case:
                case -= 1
            elif case == 0:
                yield i
            i += 1

    def split(self, a: int, b: int, is_sep) -> list:
        parts, seps, start = [], [], a
        for i in self.top(a, b):
            if is_sep(i):
                parts.append((start, i))
                seps.append(i)
                start = i + 1
        parts.append((start, b))
        return parts, seps

    def list_cuts(self, parts: list, seps: list, label: str) -> None:
        if len(parts) < 2:
            return
        for n, (pa, pb) in enumerate(parts):
            if n < len(parts) - 1:
                self.cuts.append((f"{label} {n}", parts[n][0], parts[n + 1][0]))
            else:
                self.cuts.append((f"{label} {n}", seps[n - 1], pb))

    def conjuncts(self, a: int, b: int) -> list:
        """The AND-conjunct spans of [a, b), flattened through grouping parentheses,
        each paired with the span it can be cut from (with one adjacent AND)."""
        if self.punct(a, "(") and self.match.get(a) == b - 1:
            return self.conjuncts(a + 1, b - 1)
        parts, seps = self.split(a, b, lambda i: self.kw(i, "and"))
        if len(parts) == 1:
            return [(a, b, None)]
        out = []
        for n, (pa, pb) in enumerate(parts):
            cut = (pa, parts[n + 1][0]) if n < len(parts) - 1 else (seps[n - 1], pb)
            inner = self.conjuncts(pa, pb)
            if len(inner) > 1:
                out.extend(inner)
            else:
                out.append((pa, pb, cut))
        return out

    def select(self, s: int, e: int) -> None:
        clause = {}
        joins = []
        for i in self.top(s + 1, e):
            t = self.toks[i]
            if t.kind != "kw":
                continue
            if t.text in ("from", "where", "order", "limit") and t.text not in clause:
                clause[t.text] = i
            elif t.text == "join":
                start = (
                    i - 1
                    if (i > s and (self.kw(i - 1, "left") or self.kw(i - 1, "inner")))
                    else i
                )
                joins.append({"start": start})
            elif t.text == "on" and joins and "on" not in joins[-1]:
                joins[-1]["on"] = i
        ends = sorted(
            v for k, v in clause.items() if k in ("where", "order", "limit")
        ) + [e]
        stop = lambda i: min(
            x for x in ends + [j["start"] for j in joins if j["start"] > i] if x > i
        )
        items_end = clause.get("from", e)
        parts, seps = self.split(s + 1, items_end, lambda i: self.punct(i, ","))
        self.list_cuts(parts, seps, "select item")
        for n, j in enumerate(joins):
            j_end = stop(j["start"])
            self.cuts.append((f"join {n}", j["start"], j_end))
            if "on" in j:
                cs = self.conjuncts(j["on"] + 1, j_end)
                for m, (_, _, cut) in enumerate(cs):
                    if cut is not None:
                        self.cuts.append(
                            (f"ON conjunct {m} of join {n}", cut[0], cut[1])
                        )
        if "where" in clause:
            w_end = stop(clause["where"])
            cs = self.conjuncts(clause["where"] + 1, w_end)
            if len(cs) == 1:
                self.cuts.append(("WHERE", clause["where"], w_end))
            else:
                for m, (_, _, cut) in enumerate(cs):
                    self.cuts.append((f"WHERE conjunct {m}", cut[0], cut[1]))
        if "order" in clause:
            o_end = stop(clause["order"])
            parts, seps = self.split(
                clause["order"] + 2, o_end, lambda i: self.punct(i, ",")
            )
            if len(parts) == 1:
                self.cuts.append(("ORDER BY", clause["order"], o_end))
            else:
                self.list_cuts(parts, seps, "ORDER BY key")
        if "limit" in clause:
            self.cuts.append(("LIMIT", clause["limit"], min(clause["limit"] + 2, e)))
        i = s + 1
        while i < e:
            if (
                self.kw(i, "in")
                and i + 2 < e
                and self.punct(i + 1, "(")
                and self.kw(i + 2, "select")
                and (i + 1) in self.match
            ):
                close = self.match[i + 1]
                self.select(i + 2, close)
                i = close + 1
                continue
            i += 1


def statement_reductions(sql: str) -> list:
    cutter = _Cutter(sql)
    if not cutter.kw(0, "select"):
        return []
    cutter.select(0, len(cutter.toks) - 1)
    out, seen = [], set()
    for label, a, b in cutter.cuts:
        text = cutter.text_without(a, b)
        if text and text not in seen:
            seen.add(text)
            out.append((label, text))
    return out
