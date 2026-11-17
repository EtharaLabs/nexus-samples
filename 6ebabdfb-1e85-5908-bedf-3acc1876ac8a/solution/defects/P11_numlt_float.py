"""P11 (section 4). numLt converts its operands to floating-point first, so two large
integers that are nearest the same float compare equal and the strict comparison that
should hold does not. A reader who writes a floating-point comparison shares the
engine's answer, so differential testing against such an evaluator sees no difference;
the defect is decidable only from the sentence that fixes exact comparison."""
TARGET = "conditions.py"
OLD = '''def _as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KindError("numLt needs a numeric value")
    return value'''
NEW = '''def _as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KindError("numLt needs a numeric value")
    return float(value)'''
