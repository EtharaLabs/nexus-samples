"""P3, answer, binder annotation, one subquery level.

Section 5 says a column reference carries the collation its column declares wherever
it is written, including inside the subquery of an IN or a NOT IN, and that resolving
a name in an inner scope never changes it. This binder resolves a subquery's columns
under the default collation, so a NOCASE column compared inside a subquery's WHERE
compares case-sensitively.

Nothing that binds its queries with this binder can see it: the wrong annotation
reaches such a checker and the engine alike, so the two agree. A subquery with no
comparison inside it is unaffected, since the collation of the outer comparison is
decided by the outer operand.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _common import patch

OLD = """        col.collation = column.collation
        return col"""

NEW = """        col.collation = T.BINARY if self.nested else column.collation
        return col"""

raise SystemExit(patch("tarn/bind.py", OLD, NEW, "P3"))
