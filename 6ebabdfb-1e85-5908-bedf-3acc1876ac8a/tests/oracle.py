"""An independent reading of the specification.

Written from SPEC.md, not from the engine. It borrows validation and the digest from
wardshape and implements sections 3 to 9 on its own, so a defect in the engine's
matching, conditions, closure, precedence or explain cannot hide behind a shared
evaluator. `answer(verb, world, query)` returns the specified output or raises
OracleError carrying the WARD code the specification assigns.
"""

import wardshape


class OracleError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.code = code


# --- section 3: glob -------------------------------------------------------
def glob_match(pattern, text):
    # dynamic programming over pattern x text; '*' spans any run, '?' one char.
    n, m = len(pattern), len(text)
    reach = [[False] * (m + 1) for _ in range(n + 1)]
    reach[0][0] = True
    for i in range(1, n + 1):
        if pattern[i - 1] == "*":
            reach[i][0] = reach[i - 1][0]
    for i in range(1, n + 1):
        pc = pattern[i - 1]
        for j in range(1, m + 1):
            if pc == "*":
                reach[i][j] = reach[i - 1][j] or reach[i][j - 1]
            elif pc == "?" or pc == text[j - 1]:
                reach[i][j] = reach[i - 1][j - 1]
    return reach[n][m]


def nonwild(pattern):
    return sum(1 for c in pattern if c != "*" and c != "?")


def ascii_fold(text):
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


# --- section 4: conditions -------------------------------------------------
_SCALAR_OPS = {"equals", "equalsFold", "glob", "numLt"}
_SET_OPS = {"anyOf", "allOf"}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OracleError("WARD-203", "numLt needs a number")
    return value


def _kind_of(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _equal(a, b):
    """Section 4: an element equals a listed value only with the same kind and value."""
    return _kind_of(a) == _kind_of(b) and a == b


def cond_holds(cond, context):
    op, values = cond["op"], cond["values"]
    key = cond["key"]
    present = key in context
    raw = context.get(key)
    elements = raw if isinstance(raw, list) else ([raw] if present else [])

    if op in _SCALAR_OPS:
        if not present:
            return False
        if isinstance(raw, list):
            raise OracleError("WARD-203", f"{op} needs a single value")
        if op == "numLt":
            left = _number(raw)
            return any(left < _number(w) for w in values)
        if not isinstance(raw, str):
            raise OracleError("WARD-203", f"{op} needs a string")
        if op == "equals":
            return raw in values
        if op == "equalsFold":
            folded = ascii_fold(raw)
            return any(isinstance(w, str) and ascii_fold(w) == folded for w in values)
        return any(isinstance(w, str) and glob_match(w, raw) for w in values)

    if op in _SET_OPS:
        if op == "anyOf":
            return any(_equal(e, w) for e in elements for w in values)
        return all(
            any(_equal(e, w) for w in values) for e in elements
        )  # allOf, vacuously True when empty

    raise OracleError("WARD-211", f"no such operator {op!r}")


# --- section 5: closure ----------------------------------------------------
def closure(world, principal):
    roles = world["roles"]
    if principal not in world["principals"]:
        raise OracleError("WARD-210", f"no such principal {principal!r}")

    def resolve(name):
        if name not in roles:
            raise OracleError("WARD-210", f"no such role {name!r}")
        return roles[name]

    # cycle detection by colouring
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {}

    def visit(name):
        resolve(name)
        colour[name] = GREY
        for parent in roles[name].get("inherits", []):
            c = colour.get(parent, WHITE)
            if c == GREY:
                raise OracleError("WARD-220", f"cycle through {parent!r}")
            if c == WHITE:
                visit(parent)
        colour[name] = BLACK

    direct = world["principals"][principal].get("roles", [])
    for name in direct:
        visit(name)

    # shallowest depth by relaxation to a fixed point
    depth = {name: 0 for name in direct}
    changed = True
    while changed:
        changed = False
        for name in list(depth):
            for parent in roles[name].get("inherits", []):
                cand = depth[name] + 1
                if parent not in depth or cand < depth[parent]:
                    depth[parent] = cand
                    changed = True
    return depth


# --- sections 6, 7, 9 ------------------------------------------------------
def _action_ok(st, action):
    if "action" in st:
        return any(glob_match(p, action) for p in st["action"])
    return not any(glob_match(p, action) for p in st["notAction"])


def _resource_ok(st, resource):
    if "resource" in st:
        return any(glob_match(p, resource) for p in st["resource"])
    # notResource: the statement matches when no pattern matches; an empty list
    # excludes nothing and so matches every resource.
    return not any(glob_match(p, resource) for p in st["notResource"])


def _matches(st, world, query):
    if not _action_ok(st, query["action"]):
        return False
    if not _resource_ok(st, query["resource"]):
        return False
    context = query.get("context", {})
    results = [
        cond_holds(c, context) for c in st.get("when", [])
    ]  # evaluate every condition
    return all(results)


def _specificity(st, action):
    if "action" not in st:
        return 0
    hits = [nonwild(p) for p in st["action"] if glob_match(p, action)]
    return max(hits) if hits else 0


def _ordered(world, query):
    depth = closure(world, query["principal"])
    action = query["action"]
    candidates = []
    for policy in world["policies"]:
        if policy["attach"] in depth:
            d = depth[policy["attach"]]
            for st in policy["statements"]:
                if _matches(st, world, query):
                    rank = (
                        -_specificity(st, action),
                        0 if st["effect"] == "deny" else 1,
                        d,
                        st["id"],
                    )
                    candidates.append((rank, st))
    candidates.sort(key=lambda pair: pair[0])
    return candidates


def answer(verb, world, query):
    wardshape.validate_world(world)
    wardshape.validate_query(query)
    ordered = _ordered(world, query)
    if verb == "decide":
        return {"decision": ordered[0][1]["effect"] if ordered else "deny"}
    if verb == "explain":
        return {"deciding": ordered[0][1]["id"] if ordered else None}
    raise OracleError("WARD-000", f"unknown verb {verb!r}")
