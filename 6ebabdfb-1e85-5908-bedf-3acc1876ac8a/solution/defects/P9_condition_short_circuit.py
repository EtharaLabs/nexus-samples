"""P9 (section 4). The engine stops at the first condition that is FALSE and does not
evaluate the rest, so an error that a later condition would raise is swallowed. The
departure needs a when list whose first condition is FALSE and whose second would
raise, a pairing a random world rarely writes."""
TARGET = "decide.py"
OLD = '''def conditions_hold(statement, context) -> bool:
    results = [conditions.evaluate(c, context) for c in statement.get("when", [])]
    return all(results)'''
NEW = '''def conditions_hold(statement, context) -> bool:
    return all(conditions.evaluate(c, context) for c in statement.get("when", []))'''
