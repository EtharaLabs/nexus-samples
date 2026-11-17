"""P4 (section 4). `allOf` over a key that holds no elements returns FALSE instead of
the vacuous TRUE the specification requires, so a statement whose only condition is an
`allOf` on an absent key stops applying."""

TARGET = "conditions.py"
OLD = """        # allOf: every context value is among the listed values. With no context
        # values the condition is vacuously TRUE.
        return all(any(same(c, w) for w in values) for c in members)"""
NEW = """        # allOf: every context value is among the listed values.
        return bool(members) and all(any(same(c, w) for w in values) for c in members)"""
