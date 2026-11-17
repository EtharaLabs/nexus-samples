"""EXPLAIN rendering.

One line per physical operator, two spaces of indentation per level, children in
input order.
"""
def render(op) -> str:
    lines = []
    _walk(op, 0, lines)
    return "\n".join(lines)


def _walk(op, depth: int, lines: list) -> None:
    lines.append("  " * depth + op.label())
    for child in op.children():
        _walk(child, depth + 1, lines)
