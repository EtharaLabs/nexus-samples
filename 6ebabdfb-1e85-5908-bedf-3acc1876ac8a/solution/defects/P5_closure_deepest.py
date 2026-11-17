"""P5 (section 5). A role reached along several paths is recorded at its deepest
depth instead of its shallowest, which changes the depth tie-break in section 6 for a
role reachable by two paths of different length."""
TARGET = "closure.py"
OLD = '''                if parent not in depth or depth[parent] > d + 1:'''
NEW = '''                if parent not in depth or depth[parent] < d + 1:'''
