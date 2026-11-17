
from . import ast_nodes as A
from .lex import tokenize
from .types import ParseError

COMPARISONS = {"=", "<>", "!=", "<", "<=", ">", ">="}


class Parser:
    def __init__(self, sql: str) -> None:
        self.tokens = tokenize(sql)
        self.i = 0

    # token helpers -----------------------------------------------------
    @property
    def cur(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept_kw(self, word: str) -> bool:
        if self.cur.is_kw(word):
            self.i += 1
            return True
        return False

    def expect_kw(self, word: str):
        if not self.accept_kw(word):
            raise ParseError(f"expected {word.upper()}, found {self.cur.text!r}")

    def accept_punct(self, text: str) -> bool:
        if self.cur.kind == "punct" and self.cur.text == text:
            self.i += 1
            return True
        return False

    def expect_punct(self, text: str):
        if not self.accept_punct(text):
            raise ParseError(f"expected {text!r}, found {self.cur.text!r}")

    def expect_ident(self) -> str:
        if self.cur.kind != "ident":
            raise ParseError(f"expected an identifier, found {self.cur.text!r}")
        return self.advance().value

    # statements --------------------------------------------------------
    def parse_select(self) -> A.Select:
        self.expect_kw("select")
        items = self.parse_select_list()
        self.expect_kw("from")
        source = self.parse_table_ref()
        joins = []
        while True:
            if self.accept_kw("left"):
                self.accept_kw("inner")
                self.expect_kw("join")
                kind = "left"
            elif self.accept_kw("inner"):
                self.expect_kw("join")
                kind = "inner"
            elif self.accept_kw("join"):
                kind = "inner"
            else:
                break
            table = self.parse_table_ref()
            self.expect_kw("on")
            joins.append(A.JoinClause(kind=kind, table=table, on=self.parse_expr()))
        where = self.parse_expr() if self.accept_kw("where") else None
        order_by = []
        if self.accept_kw("order"):
            self.expect_kw("by")
            while True:
                expr = self.parse_expr()
                direction = "asc"
                if self.accept_kw("desc"):
                    direction = "desc"
                else:
                    self.accept_kw("asc")
                order_by.append(A.OrderItem(expr=expr, direction=direction))
                if not self.accept_punct(","):
                    break
        limit = None
        if self.accept_kw("limit"):
            if self.cur.kind != "num":
                raise ParseError("LIMIT needs an integer literal")
            limit = int(self.advance().value)
        return A.Select(
            items=items,
            source=source,
            joins=joins,
            where=where,
            order_by=order_by,
            limit=limit,
        )

    def parse_select_list(self) -> list:
        items = []
        while True:
            if self.accept_punct("*"):
                items.append(("*", None))
            else:
                expr = self.parse_expr()
                alias = None
                if self.accept_kw("as"):
                    alias = self.expect_ident()
                items.append((expr, alias))
            if not self.accept_punct(","):
                break
        return items

    def parse_table_ref(self) -> A.TableRef:
        name = self.expect_ident()
        alias = name
        if self.accept_kw("as"):
            alias = self.expect_ident()
        elif self.cur.kind == "ident":
            alias = self.expect_ident()
        return A.TableRef(table=name, alias=alias)

    # expressions -------------------------------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.accept_kw("or"):
            node = A.BinOp("or", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.accept_kw("and"):
            node = A.BinOp("and", node, self.parse_not())
        return node

    def parse_not(self):
        if self.accept_kw("not"):
            return A.Not(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self):
        node = self.parse_add()
        while True:
            if self.cur.kind == "punct" and self.cur.text in COMPARISONS:
                op = self.advance().text
                node = A.BinOp("<>" if op == "!=" else op, node, self.parse_add())
                continue
            if self.cur.is_kw("is"):
                self.i += 1
                if self.accept_kw("not"):
                    if self.accept_kw("distinct"):
                        self.expect_kw("from")
                        node = A.IsNotDistinct(node, self.parse_add())
                        continue
                    self.expect_kw("null")
                    node = A.IsNull(node, negated=True)
                    continue
                self.expect_kw("null")
                node = A.IsNull(node, negated=False)
                continue
            negated = False
            save = self.i
            if self.accept_kw("not"):
                negated = True
            if self.accept_kw("like"):
                node = A.Like(node, self.parse_add(), negated=negated)
                continue
            if self.accept_kw("in"):
                self.expect_punct("(")
                sub = self.parse_select()
                self.expect_punct(")")
                node = A.InSubquery(node, sub, negated=negated)
                continue
            self.i = save
            break
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.cur.kind == "punct" and self.cur.text in ("+", "-"):
            op = self.advance().text
            node = A.BinOp(op, node, self.parse_mul())
        return node

    def parse_mul(self):
        node = self.parse_unary()
        while self.cur.kind == "punct" and self.cur.text in ("*", "/"):
            op = self.advance().text
            node = A.BinOp(op, node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.cur.kind == "punct" and self.cur.text == "-":
            self.i += 1
            return A.BinOp("-", A.Lit(0), self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.cur
        if tok.kind == "num":
            self.i += 1
            return A.Lit(tok.value)
        if tok.kind == "str":
            self.i += 1
            return A.Lit(tok.value)
        if tok.is_kw("null"):
            self.i += 1
            return A.Lit(None)
        if tok.is_kw("true"):
            self.i += 1
            return A.Lit(True)
        if tok.is_kw("false"):
            self.i += 1
            return A.Lit(False)
        if tok.is_kw("coalesce"):
            self.i += 1
            self.expect_punct("(")
            args = [self.parse_expr()]
            while self.accept_punct(","):
                args.append(self.parse_expr())
            self.expect_punct(")")
            return A.Coalesce(args)
        if tok.is_kw("case"):
            self.i += 1
            whens = []
            while self.accept_kw("when"):
                cond = self.parse_expr()
                self.expect_kw("then")
                whens.append((cond, self.parse_expr()))
            otherwise = A.Lit(None)
            if self.accept_kw("else"):
                otherwise = self.parse_expr()
            self.expect_kw("end")
            if not whens:
                raise ParseError("CASE needs at least one WHEN branch")
            return A.Case(whens=whens, otherwise=otherwise)
        if self.accept_punct("("):
            node = self.parse_expr()
            self.expect_punct(")")
            return node
        if tok.kind == "ident":
            self.i += 1
            if self.accept_punct("."):
                return A.Col(qualifier=tok.value, name=self.expect_ident())
            return A.Col(qualifier=None, name=tok.value)
        raise ParseError(f"unexpected token {tok.text!r}")


def parse(sql: str) -> A.Select:
    parser = Parser(sql)
    stmt = parser.parse_select()
    if parser.cur.kind != "eof":
        raise ParseError(f"trailing input at {parser.cur.text!r}")
    return stmt
