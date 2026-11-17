"""P12 (section 4). anyOf compares an element to a listed value by their text form,
so the number 5 equals the string "5". Section 4 says equality is by exact value and
kind. A reader who compares by text shares the engine's answer, so differential
testing misses it; the defect is decidable only from the kind rule."""

TARGET = "conditions.py"
OLD = """        if op == "anyOf":
            return any(same(c, w) for c in members for w in values)"""
NEW = """        if op == "anyOf":
            return any(str(c) == str(w) for c in members for w in values)"""
