"""The engine entry points: decide and explain (specification sections 7 and 9)."""

from . import canon, decide
from .errors import WardError

__all__ = ["answer", "WardError"]


def answer(verb, world, query):
    """Run one call. `verb` is 'decide' or 'explain'. Returns the specified output."""
    canon.validate_world(world)
    canon.validate_query(query)
    matching = decide.deciding(world, query)
    if verb == "decide":
        decision = matching[0][0]["effect"] if matching else "deny"
        return {"decision": decision}
    if verb == "explain":
        return {"deciding": matching[0][0]["id"] if matching else None}
    raise WardError(f"unknown verb {verb!r}")
