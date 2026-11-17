"""P1 (section 8). The action-index classifies a `?`-pattern as wildcard-free, so a
statement whose action pattern contains `?` is bucketed by its literal text and is
never found on the index path. It is missed only when the index path runs: nine or
more effective statements and no `notAction`. The scanning path is unaffected."""
TARGET = "decide.py"
OLD = '''def _is_wildcard_free(pattern) -> bool:
    return "*" not in pattern and "?" not in pattern'''
NEW = '''def _is_wildcard_free(pattern) -> bool:
    return "*" not in pattern'''
