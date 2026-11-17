"""Validation and canonical digest of a call payload.

A call payload is `{"world": <world>, "query": <query>}`. The world is the data the
decision is made over; the query names the principal, action, resource and context.
The service validates both and refuses an invalid payload with WARD-400, spending no
call. The log identifies a world by a digest over every key and value of its
canonical form, so the same world written with its keys in another order has the same
digest, while `1` and `1.0`, or a field written out and the same field left to its
default, give different digests.

This module is the only part shared between the engine, the service and the graders.
"""

import hashlib
import json

from .errors import InvalidInput

_KINDS = ("allow", "deny")
_SCALAR = (str, int, float, bool)


def _ident(name) -> bool:
    return (
        isinstance(name, str)
        and name != ""
        and all(c.isalnum() or c in "_.:-/" for c in name)
    )


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_world(world) -> None:
    if not isinstance(world, dict):
        raise InvalidInput("world must be an object")
    for key in ("roles", "principals", "policies"):
        if key not in world:
            raise InvalidInput(f"world is missing {key!r}")
    if not isinstance(world["roles"], dict):
        raise InvalidInput("roles must be an object")
    if not isinstance(world["principals"], dict):
        raise InvalidInput("principals must be an object")
    if not isinstance(world["policies"], list):
        raise InvalidInput("policies must be a list")

    for name, body in world["roles"].items():
        if not _ident(name):
            raise InvalidInput(f"role name {name!r} is not an identifier")
        if not isinstance(body, dict):
            raise InvalidInput(f"role {name!r} must be an object")
        inh = body.get("inherits", [])
        if not _is_str_list(inh):
            raise InvalidInput(f"role {name!r} inherits must be a list of names")

    for name, body in world["principals"].items():
        if not _ident(name):
            raise InvalidInput(f"principal name {name!r} is not an identifier")
        if not isinstance(body, dict) or not _is_str_list(body.get("roles", [])):
            raise InvalidInput(f"principal {name!r} must carry a list of roles")

    seen_pid, seen_sid = set(), set()
    for policy in world["policies"]:
        if not isinstance(policy, dict):
            raise InvalidInput("every policy must be an object")
        pid = policy.get("id")
        if not _ident(pid):
            raise InvalidInput(f"policy id {pid!r} is not an identifier")
        if pid in seen_pid:
            raise InvalidInput(f"duplicate policy id {pid!r}")
        seen_pid.add(pid)
        if not _ident(policy.get("attach")):
            raise InvalidInput(f"policy {pid!r} must attach to a role name")
        if not isinstance(policy.get("statements"), list):
            raise InvalidInput(f"policy {pid!r} statements must be a list")
        for st in policy["statements"]:
            _validate_statement(st, seen_sid)


def _validate_statement(st, seen_sid) -> None:
    if not isinstance(st, dict):
        raise InvalidInput("every statement must be an object")
    sid = st.get("id")
    if not _ident(sid):
        raise InvalidInput(f"statement id {sid!r} is not an identifier")
    if sid in seen_sid:
        raise InvalidInput(f"duplicate statement id {sid!r}")
    seen_sid.add(sid)
    if st.get("effect") not in _KINDS:
        raise InvalidInput(f"statement {sid!r} effect must be allow or deny")
    if ("action" in st) == ("notAction" in st):
        raise InvalidInput(f"statement {sid!r} needs exactly one of action, notAction")
    if ("resource" in st) == ("notResource" in st):
        raise InvalidInput(
            f"statement {sid!r} needs exactly one of resource, notResource"
        )
    for field in ("action", "notAction", "resource", "notResource"):
        if field in st and not _is_str_list(st[field]):
            raise InvalidInput(f"statement {sid!r} {field} must be a list of patterns")
    for cond in st.get("when", []):
        if not isinstance(cond, dict):
            raise InvalidInput(f"statement {sid!r} has a non-object condition")
        if not isinstance(cond.get("key"), str) or not isinstance(cond.get("op"), str):
            raise InvalidInput(f"statement {sid!r} condition needs a string key and op")
        if not isinstance(cond.get("values"), list):
            raise InvalidInput(f"statement {sid!r} condition values must be a list")


def validate_query(query) -> None:
    if not isinstance(query, dict):
        raise InvalidInput("query must be an object")
    for key in ("principal", "action", "resource"):
        if not isinstance(query.get(key), str) or query.get(key) == "":
            raise InvalidInput(f"query {key} must be a non-empty string")
    ctx = query.get("context", {})
    if not isinstance(ctx, dict):
        raise InvalidInput("query context must be an object")
    for key, value in ctx.items():
        if not isinstance(key, str):
            raise InvalidInput("context keys must be strings")
        if isinstance(value, list):
            if not all(isinstance(v, _SCALAR) for v in value):
                raise InvalidInput(f"context {key!r} list holds a non-scalar value")
        elif not isinstance(value, _SCALAR):
            raise InvalidInput(f"context {key!r} must be a scalar or a list of scalars")


def _canon(value):
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        return ["real", repr(value)]
    if isinstance(value, str):
        return ["str", value]
    if value is None:
        return ["null"]
    if isinstance(value, list):
        return ["list", [_canon(v) for v in value]]
    if isinstance(value, dict):
        return ["obj", [[k, _canon(value[k])] for k in sorted(value)]]
    raise InvalidInput(f"cannot canonicalize {value!r}")


def canon_text(value) -> str:
    return json.dumps(_canon(value), separators=(",", ":"), ensure_ascii=True)


def world_digest(world) -> str:
    return hashlib.sha256(canon_text(world).encode("utf-8")).hexdigest()[:16]


def query_digest(query) -> str:
    return hashlib.sha256(canon_text(query).encode("utf-8")).hexdigest()[:16]
