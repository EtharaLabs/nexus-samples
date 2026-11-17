"""P8 (section 9). The statement-id tie-break is reversed. When the top matches tie on
specificity, effect and depth and share one effect, the decision is unchanged but
`explain` returns the wrong deciding id. The defect shows only through `explain`."""
TARGET = "decide.py"
OLD = '''def _tie_id(sid):
    """The last tie-break: statement id ascending."""
    return sid'''
NEW = '''def _tie_id(sid):
    """The last tie-break: statement id ascending."""
    return tuple(-ord(c) for c in sid)'''
