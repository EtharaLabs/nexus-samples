"""Value kinds, collation keys, and the engine error codes.

"""
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
BOOLEAN = "BOOLEAN"
NULL = "NULL"

BINARY = "BINARY"
NOCASE = "NOCASE"

NUMERIC_TYPES = (INTEGER, REAL)


class TarnError(Exception):

    code = "TARN-000"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message


class ParseError(TarnError):
    code = "TARN-101"


class UnknownTable(TarnError):
    code = "TARN-200"


class UnknownColumn(TarnError):
    code = "TARN-201"


class AmbiguousColumn(TarnError):
    code = "TARN-202"


class TypeMismatch(TarnError):
    code = "TARN-203"


class DivisionByZero(TarnError):
    code = "TARN-301"


def kind(value) -> str:
    """The value kind of a runtime value."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int):
        return INTEGER
    if isinstance(value, float):
        return REAL
    if isinstance(value, str):
        return TEXT
    raise TypeMismatch(f"unsupported runtime value {value!r}")


def is_numeric(value) -> bool:
    return kind(value) in NUMERIC_TYPES


def ascii_fold(text: str) -> str:
    """Fold only the 26 ASCII letters A-Z.

    Characters outside A-Z are returned unchanged, so 'E' with an acute accent is
    never folded onto its lowercase form.
    """
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(ord(ch) + 32))
        else:
            out.append(ch)
    return "".join(out)


def collate_key(text: str, collation: str):
    """The comparison key of a TEXT value under `collation`."""
    if collation == NOCASE:
        return ascii_fold(text)
    return text


def order_key(value, collation: str):
    """Sort key placing NULL before every non-NULL value."""
    if value is None:
        return (0,)
    if isinstance(value, str):
        return (1, collate_key(value, collation))
    if isinstance(value, bool):
        return (1, int(value))
    return (1, value)
