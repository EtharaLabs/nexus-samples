"""P6 (section 4). `equalsFold` folds with a full Unicode lower-casing rather than the
twenty-six ASCII letters only, so a context value carrying a non-ASCII letter folds to
match a listed value it should stay distinct from."""
TARGET = "conditions.py"
OLD = '''def fold(text: str) -> str:
    """Fold the twenty-six ASCII letters A-Z to lower case and nothing else."""
    out = []
    for ch in text:
        out.append(chr(ord(ch) + 32) if "A" <= ch <= "Z" else ch)
    return "".join(out)'''
NEW = '''def fold(text: str) -> str:
    """Fold the twenty-six ASCII letters A-Z to lower case and nothing else."""
    return text.lower()'''
