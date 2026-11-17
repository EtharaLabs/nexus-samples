"""Expression and statement nodes."""
from dataclasses import dataclass, field


@dataclass
class Lit:
    value: object


@dataclass
class Col:
    qualifier: str | None
    name: str
    # filled in by bind.py
    alias: str | None = None
    type: str | None = None
    collation: str | None = None

    @property
    def key(self) -> str:
        return f"{self.alias}.{self.name}"


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class Not:
    operand: object


@dataclass
class IsNull:
    operand: object
    negated: bool = False


@dataclass
class IsNotDistinct:
    left: object
    right: object


@dataclass
class Like:
    operand: object
    pattern: object
    negated: bool = False


@dataclass
class Coalesce:
    args: list


@dataclass
class Case:
    whens: list  # [(cond, result)]
    otherwise: object


@dataclass
class InSubquery:
    operand: object
    select: object
    negated: bool = False


@dataclass
class TableRef:
    table: str
    alias: str


@dataclass
class JoinClause:
    kind: str  # 'inner' | 'left'
    table: TableRef
    on: object


@dataclass
class OrderItem:
    expr: object
    direction: str = "asc"


@dataclass
class Select:
    items: list  # [(expr|'*', alias|None)]
    source: TableRef = None
    joins: list = field(default_factory=list)
    where: object = None
    order_by: list = field(default_factory=list)
    limit: int | None = None
