"""Glob matching for action and resource patterns (specification section 3).

`*` matches any run of characters including the empty run. `?` matches exactly one
character and never the empty string. Every other character matches itself, and the
match is case sensitive.
"""


def matches(pattern: str, text: str) -> bool:
    return _match(pattern, 0, text, 0)


def _match(p: str, pi: int, s: str, si: int) -> bool:
    while pi < len(p):
        ch = p[pi]
        if ch == "*":
            if pi + 1 == len(p):
                return True
            for skip in range(si, len(s) + 1):
                if _match(p, pi + 1, s, skip):
                    return True
            return False
        if si >= len(s):
            return False
        if ch == "?":
            si += 1
            pi += 1
            continue
        if p[pi] != s[si]:
            return False
        si += 1
        pi += 1
    return si == len(s)


def nonwild_count(pattern: str) -> int:
    """The number of characters in `pattern` that are neither `*` nor `?`.

    Specification section 6: a statement's action-specificity is this count for the
    pattern that matched the request's action.
    """
    return sum(1 for ch in pattern if ch not in ("*", "?"))
