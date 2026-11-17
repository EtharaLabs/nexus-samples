"""Every way to take exactly one element away from a finding, and nothing else.

A finding is `{input: <world>, request: <query>}`. A reduction removes one listed
element and changes nothing else. A reduction that leaves an invalid world or query
is still a reduction: the grader runs it and finds the defect no longer shown,
because the case no longer runs.
"""

import copy


def _without_index(items, i):
    return items[:i] + items[i + 1 :]


def world_reductions(world):
    out = []

    for role in list(world["roles"]):
        w = copy.deepcopy(world)
        del w["roles"][role]
        out.append((f"role:{role}", w))

    for role, body in world["roles"].items():
        for i, _ in enumerate(body.get("inherits", [])):
            w = copy.deepcopy(world)
            w["roles"][role]["inherits"] = _without_index(
                w["roles"][role]["inherits"], i
            )
            out.append((f"inherit:{role}:{i}", w))

    for pr in list(world["principals"]):
        w = copy.deepcopy(world)
        del w["principals"][pr]
        out.append((f"principal:{pr}", w))

    for pr, body in world["principals"].items():
        for i, _ in enumerate(body.get("roles", [])):
            w = copy.deepcopy(world)
            w["principals"][pr]["roles"] = _without_index(
                w["principals"][pr]["roles"], i
            )
            out.append((f"principal-role:{pr}:{i}", w))

    for pi, policy in enumerate(world["policies"]):
        w = copy.deepcopy(world)
        w["policies"] = _without_index(w["policies"], pi)
        out.append((f"policy:{policy['id']}", w))

    for pi, policy in enumerate(world["policies"]):
        for si, st in enumerate(policy["statements"]):
            w = copy.deepcopy(world)
            w["policies"][pi]["statements"] = _without_index(
                w["policies"][pi]["statements"], si
            )
            out.append((f"statement:{st['id']}", w))

    for pi, policy in enumerate(world["policies"]):
        for si, st in enumerate(policy["statements"]):
            for field in ("action", "notAction", "resource", "notResource"):
                if field in st and len(st[field]) > 1:
                    for k in range(len(st[field])):
                        w = copy.deepcopy(world)
                        w["policies"][pi]["statements"][si][field] = _without_index(
                            st[field], k
                        )
                        out.append((f"pattern:{st['id']}:{field}:{k}", w))
            for ci, _ in enumerate(st.get("when", [])):
                w = copy.deepcopy(world)
                target = w["policies"][pi]["statements"][si]
                reduced = _without_index(st["when"], ci)
                if reduced:
                    target["when"] = reduced
                else:
                    del target[
                        "when"
                    ]  # the last condition leaves a statement with none
                out.append((f"condition:{st['id']}:{ci}", w))
                cond = st["when"][ci]
                if len(cond["values"]) > 1:
                    for vi in range(len(cond["values"])):
                        w2 = copy.deepcopy(world)
                        w2["policies"][pi]["statements"][si]["when"][ci]["values"] = (
                            _without_index(cond["values"], vi)
                        )
                        out.append((f"value:{st['id']}:{ci}:{vi}", w2))
    return out


def query_reductions(query):
    out = []
    ctx = query.get("context", {})
    for key in list(ctx):
        q = copy.deepcopy(query)
        del q["context"][key]
        out.append((f"context-key:{key}", q))
    for key, value in ctx.items():
        if isinstance(value, list) and len(value) > 1:
            for i in range(len(value)):
                q = copy.deepcopy(query)
                q["context"][key] = _without_index(value, i)
                out.append((f"context-value:{key}:{i}", q))
    return out


def all_reductions(world, query):
    out = [("world", lab, w, query) for lab, w in world_reductions(world)]
    out += [("query", lab, world, q) for lab, q in query_reductions(query)]
    return out
