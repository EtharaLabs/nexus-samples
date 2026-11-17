"""P3 (section 6). The precedence order places depth before effect, so among equal
specificity matches a shallower allow beats a deeper deny. The departure shows only
when two matches have equal specificity, opposite effects, and different inheritance
depths, which a random world rarely produces."""
TARGET = "decide.py"
OLD = '''def order_key(statement, depth, action):
    """Section 6 precedence: specificity, then effect, then depth, then id."""
    return (
        -specificity(statement, action),
        _deny_first(statement),
        depth,
        _tie_id(statement["id"]),
    )'''
NEW = '''def order_key(statement, depth, action):
    """Section 6 precedence: specificity, then effect, then depth, then id."""
    return (
        -specificity(statement, action),
        depth,
        _deny_first(statement),
        _tie_id(statement["id"]),
    )'''
