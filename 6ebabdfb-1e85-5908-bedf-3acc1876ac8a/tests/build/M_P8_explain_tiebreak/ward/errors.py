"""Domain errors. Each carries the WARD code the specification assigns it."""


class WardError(Exception):
    code = "WARD-000"

    def __init__(self, message: str = "") -> None:
        super().__init__(f"{self.code}: {message}" if message else self.code)
        self.message = message


class InvalidInput(WardError):
    code = "WARD-400"


class UnknownName(WardError):
    code = "WARD-210"


class UnknownOperator(WardError):
    code = "WARD-211"


class KindError(WardError):
    code = "WARD-203"


class RoleCycle(WardError):
    code = "WARD-220"
