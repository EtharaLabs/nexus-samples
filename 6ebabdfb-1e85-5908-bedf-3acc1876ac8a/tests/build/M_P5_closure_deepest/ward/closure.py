"""Role closure (specification section 5).

A principal's effective roles are its own roles at depth 0 and everything reachable
through `inherits`. A role reached by several paths is recorded at its shallowest
depth. Depth breaks ties between matching statements in section 6 and nothing else.
A cycle in the inheritance graph is WARD-220.
"""

from .errors import RoleCycle, UnknownName


def _role(world, name):
    if name not in world["roles"]:
        raise UnknownName(f"no such role {name!r}")
    return world["roles"][name]


def _check_acyclic(world, name, on_path, done) -> None:
    if name in done:
        return
    if name in on_path:
        raise RoleCycle(f"role {name!r} inherits itself")
    on_path.add(name)
    for parent in _role(world, name).get("inherits", []):
        _check_acyclic(world, parent, on_path, done)
    on_path.discard(name)
    done.add(name)


def closure(world, principal_name) -> dict:
    if principal_name not in world["principals"]:
        raise UnknownName(f"no such principal {principal_name!r}")
    direct = world["principals"][principal_name].get("roles", [])
    for name in direct:
        _check_acyclic(world, name, set(), set())

    depth = {}
    frontier = []
    for name in direct:
        if name not in depth or depth[name] > 0:
            depth[name] = 0
        frontier.append((name, 0))
    while frontier:
        nxt = []
        for name, d in frontier:
            for parent in _role(world, name).get("inherits", []):
                if parent not in depth or depth[parent] > d + 1:
                    depth[parent] = d + 1
                    nxt.append((parent, d + 1))
        frontier = nxt
    return depth
