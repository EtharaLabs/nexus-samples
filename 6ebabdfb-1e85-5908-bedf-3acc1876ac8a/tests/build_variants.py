"""Build every engine variant from the clean source and the defect patches.

The clean engine lives in `solution/engine/ward`. This writes, under `tests/build`:
`reference` (the clean engine), `shipped` (every defect applied), and one
`M_<id>` per defect (every defect except that one, so the one defect is repaired).
It also syncs `environment/wardd/engine/ward` to `shipped`, the tree the service
serves. Scripts locate every path from their own position.

    python3 build_variants.py           build the trees
    python3 build_variants.py --check    prove each M_<id> differs from shipped by
                                         its own patch only
"""

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "solution" / "engine" / "ward"
BUILD = ROOT / "tests" / "build"
SERVICE = ROOT / "environment" / "wardd" / "engine" / "ward"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

sys.path.insert(0, str(ROOT / "solution" / "defects"))
import _common  # noqa: E402


def _fresh(dest):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SRC, dest / "ward", ignore=IGNORE)
    return dest / "ward"


def build():
    defects = _common.defect_modules()
    names = sorted(defects)

    if BUILD.exists():
        shutil.rmtree(BUILD)  # drop any renamed-away variants
    _fresh(BUILD / "reference")

    shipped = _fresh(BUILD / "shipped")
    for name in names:
        _common.apply(shipped, defects[name])

    for name in names:
        tree = _fresh(BUILD / f"M_{name}")
        for other in names:
            if other != name:
                _common.apply(tree, defects[other])

    if SERVICE.exists():
        shutil.rmtree(SERVICE)
    shutil.copytree(BUILD / "shipped" / "ward", SERVICE, ignore=IGNORE)

    print(
        f"built reference, shipped ({len(names)} defects), {len(names)} single-fix "
        f"variants; synced the service engine"
    )
    return names


def _files(tree):
    return {
        p.relative_to(tree): p.read_text(encoding="utf-8") for p in tree.rglob("*.py")
    }


def check():
    defects = _common.defect_modules()
    shipped = _files(BUILD / "shipped" / "ward")
    ok = True
    for name, defect in defects.items():
        variant = _files(BUILD / f"M_{name}" / "ward")
        differing = sorted(str(r) for r in shipped if shipped[r] != variant.get(r))
        # applying this one defect to the variant must reproduce shipped exactly
        _common.apply(BUILD / f"M_{name}" / "ward", defect)
        repaired = _files(BUILD / f"M_{name}" / "ward")
        same_as_shipped = repaired == shipped
        _common.apply(BUILD / f"M_{name}" / "ward", _Reverse(defect))  # undo
        mark = "ok" if (differing == [defect.TARGET] and same_as_shipped) else "FAIL"
        print(f"  {mark}  M_{name}: differs from shipped in {differing}")
        ok = ok and mark == "ok"
    print("each M_<id> differs from shipped by its own patch only:", ok)
    return 0 if ok else 1


class _Reverse:
    """Apply a defect in reverse, to restore a variant after the check."""

    def __init__(self, defect):
        self.__name__ = f"undo_{defect.__name__}"
        self.TARGET = defect.TARGET
        self.OLD = defect.NEW
        self.NEW = defect.OLD


def main() -> int:
    if "--check" in sys.argv:
        return check()
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
