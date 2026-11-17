"""Matching, precedence and the decision (specification sections 6, 7 and 8)."""

from . import conditions, glob
from .closure import closure


def _pattern_weight(pattern) -> int:
    """The weight of one action pattern: its count of non-wildcard characters."""
    return len(pattern)


def specificity(statement, action) -> int:
    """Action-specificity (section 6): the weight of the most specific action pattern
    that matches `action`, or 0 for a statement written with `notAction`."""
    if "action" in statement:
        hits = [
            _pattern_weight(p) for p in statement["action"] if glob.matches(p, action)
        ]
        return max(hits) if hits else 0
    return _not_action_specificity(statement)


def _not_action_specificity(statement) -> int:
    """A statement written with notAction has action-specificity 0 (section 6)."""
    return max((len(p) for p in statement["notAction"]), default=0)


def _deny_first(statement) -> int:
    """At equal specificity a `deny` is ordered before an `allow`."""
    return 0 if statement["effect"] == "deny" else 1


def _tie_id(sid):
    """The last tie-break: statement id ascending."""
    return sid


def action_matches(statement, action) -> bool:
    if "action" in statement:
        return any(glob.matches(p, action) for p in statement["action"])
    return not any(glob.matches(p, action) for p in statement["notAction"])


def resource_matches(statement, resource) -> bool:
    if "resource" in statement:
        return any(glob.matches(p, resource) for p in statement["resource"])
    return not any(glob.matches(p, resource) for p in statement["notResource"])


def conditions_hold(statement, context) -> bool:
    return all(conditions.evaluate(c, context) for c in statement.get("when", []))


def statement_matches(statement, query) -> bool:
    return (
        action_matches(statement, query["action"])
        and resource_matches(statement, query["resource"])
        and conditions_hold(statement, query.get("context", {}))
    )


def order_key(statement, depth, action):
    """Section 6 precedence: specificity, then effect, then depth, then id."""
    return (
        -specificity(statement, action),
        depth,
        _deny_first(statement),
        _tie_id(statement["id"]),
    )


def effective(world, principal):
    depth = closure(world, principal)
    out = []
    for policy in world["policies"]:
        attach = policy["attach"]
        if attach in depth:
            for st in policy["statements"]:
                out.append((st, depth[attach]))
    return out


def _uses_not_action(eff) -> bool:
    return any("notAction" in st for st, _ in eff)


def use_index(eff) -> bool:
    """The action-index fast path runs when a principal has nine or more effective
    statements and none of them is written with `notAction` (section 8)."""
    return len(eff) >= 9 and not _uses_not_action(eff)


def _is_wildcard_free(pattern) -> bool:
    return "*" not in pattern


def _build_index(eff):
    exact = {}
    wild = []
    for st, depth in eff:
        patterns = st["action"]
        wildcard_patterns = [p for p in patterns if not _is_wildcard_free(p)]
        for p in patterns:
            if _is_wildcard_free(p):
                exact[p] = [(st, depth)]
        if wildcard_patterns:
            wild.append((st, depth))
    return exact, wild


def _action_candidates_indexed(eff, action):
    exact, wild = _build_index(eff)
    out = []
    seen = set()
    for st, depth in exact.get(action, []):
        if id(st) not in seen:
            out.append((st, depth))
            seen.add(id(st))
    for st, depth in wild:
        if id(st) not in seen and action_matches(st, action):
            out.append((st, depth))
            seen.add(id(st))
    return out


def _action_candidates(eff, action):
    if use_index(eff):
        return _action_candidates_indexed(eff, action)
    return [(st, depth) for st, depth in eff if action_matches(st, action)]


def deciding(world, query):
    eff = effective(world, query["principal"])
    action = query["action"]
    by_action = _action_candidates(eff, action)
    matching = [
        (st, depth)
        for st, depth in by_action
        if resource_matches(st, query["resource"])
        and conditions_hold(st, query.get("context", {}))
    ]
    matching.sort(key=lambda item: order_key(item[0], item[1], action))
    return matching
