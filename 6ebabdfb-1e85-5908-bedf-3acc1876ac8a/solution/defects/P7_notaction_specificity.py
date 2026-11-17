"""P7 (section 6). A notAction statement is given the length of its pattern as its
action-specificity instead of 0, so a long notAction deny outranks a specific action
allow. The departure needs a notAction statement and an action statement that both
match one request, which a random world seldom arranges."""
TARGET = "decide.py"
OLD = '''def _not_action_specificity(statement) -> int:
    """A statement written with notAction has action-specificity 0 (section 6)."""
    return 0'''
NEW = '''def _not_action_specificity(statement) -> int:
    """A statement written with notAction has action-specificity 0 (section 6)."""
    return max((len(p) for p in statement["notAction"]), default=0)'''
