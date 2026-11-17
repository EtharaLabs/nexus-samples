"""Logical plan nodes."""
from dataclasses import dataclass, field


@dataclass
class LScan:
    table: str
    alias: str
    index_column: str | None = None


@dataclass
class LJoin:
    kind: str  # 'inner' | 'left'
    left: object
    right: object
    on: object
    physical: str | None = None
    key_collation: str | None = None


@dataclass
class LFilter:
    child: object
    pred: object


@dataclass
class LAntiJoin:
    """NOT IN rewritten as an anti-join on an equality key."""
    left: object
    right: object
    left_expr: object
    right_expr: object
    null_aware: bool


@dataclass
class LAntiMatch:
    """The left rows with no join partner under `on`."""
    left: object
    right: object
    on: object


@dataclass
class LNullPad:
    child: object
    pad_keys: list


@dataclass
class LUnionAll:
    left: object
    right: object


@dataclass
class LSort:
    child: object
    keys: list


@dataclass
class LLimit:
    child: object
    count: int


@dataclass
class LProject:
    child: object
    items: list = field(default_factory=list)


def children(node) -> list:
    if isinstance(node, LScan):
        return []
    if isinstance(node, (LJoin, LUnionAll)):
        return [node.left, node.right]
    if isinstance(node, (LAntiJoin, LAntiMatch)):
        return [node.left, node.right]
    if isinstance(node, (LFilter, LNullPad, LSort, LLimit, LProject)):
        return [node.child]
    return []


def scan_aliases(node) -> set:
    if isinstance(node, LScan):
        return {node.alias}
    out = set()
    for child in children(node):
        out |= scan_aliases(child)
    return out
