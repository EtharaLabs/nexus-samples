"""P10 (sections 8 and 9). On the index path the action-index keeps only the last
statement for each exact action, so when two statements share an exact action the
index drops the earlier one. The decision is unchanged when both share an effect, but
explain returns the later id instead of the smaller one the section 6 tie-break
requires. It shows only with nine or more statements, a duplicated exact action, and
explain."""
TARGET = "decide.py"
OLD = '''        for p in patterns:
            if _is_wildcard_free(p):
                exact.setdefault(p, []).append((st, depth))'''
NEW = '''        for p in patterns:
            if _is_wildcard_free(p):
                exact[p] = [(st, depth)]'''
