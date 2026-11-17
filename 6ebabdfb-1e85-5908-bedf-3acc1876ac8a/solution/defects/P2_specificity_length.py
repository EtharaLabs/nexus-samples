"""P2 (section 6). Action-specificity is counted as the pattern's length rather than
its count of non-wildcard characters, so two patterns with different wildcard counts
can tie and fall to the deny tie-break."""
TARGET = "decide.py"
OLD = '''def _pattern_weight(pattern) -> int:
    """The weight of one action pattern: its count of non-wildcard characters."""
    return glob.nonwild_count(pattern)'''
NEW = '''def _pattern_weight(pattern) -> int:
    """The weight of one action pattern: its count of non-wildcard characters."""
    return len(pattern)'''
