
from dataclasses import dataclass

from .types import ParseError

KEYWORDS = {
    "select",
    "from",
    "where",
    "join",
    "left",
    "inner",
    "on",
    "order",
    "by",
    "asc",
    "desc",
    "limit",
    "as",
    "and",
    "or",
    "not",
    "is",
    "null",
    "in",
    "like",
    "distinct",
    "coalesce",
    "case",
    "when",
    "then",
    "else",
    "end",
    "true",
    "false",
}

PUNCT = ["<=", ">=", "<>", "!=", "(", ")", ",", ".", "*", "+", "-", "/", "=", "<", ">"]


@dataclass
class Token:
    kind: str  # 'kw' | 'ident' | 'num' | 'str' | 'punct' | 'eof'
    text: str
    value: object = None
    pos: int = 0

    def is_kw(self, word: str) -> bool:
        return self.kind == "kw" and self.text == word


def tokenize(sql: str) -> list:
    tokens = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if ch == "'":
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise ParseError("unterminated string literal")
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            tokens.append(Token("str", "".join(buf), "".join(buf), i))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (sql[j].isdigit() or sql[j] == "."):
                if sql[j] == ".":
                    if seen_dot:
                        break
                    seen_dot = True
                j += 1
            text = sql[i:j]
            value = float(text) if seen_dot else int(text)
            tokens.append(Token("num", text, value, i))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            text = sql[i:j]
            low = text.lower()
            tokens.append(
                Token(
                    "kw" if low in KEYWORDS else "ident",
                    low if low in KEYWORDS else text,
                    text,
                    i,
                )
            )
            i = j
            continue
        for p in PUNCT:
            if sql.startswith(p, i):
                tokens.append(Token("punct", p, p, i))
                i += len(p)
                break
        else:
            raise ParseError(f"unexpected character {ch!r} at offset {i}")
    tokens.append(Token("eof", "", None, n))
    return tokens
