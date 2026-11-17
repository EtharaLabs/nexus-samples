"""Shared helpers for the defect patches and the variant builder.

Each defect module beside this one exposes `TARGET` (a file under the engine package,
relative to the package root), `OLD` and `NEW` (exact strings). Applying a defect
replaces `OLD` with `NEW` once in `TARGET`. The replacement is anchored on a whole
function so that each defect touches one seam and no other.
"""

import importlib.util
import pathlib


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def defect_modules():
    here = pathlib.Path(__file__).resolve().parent
    return {p.stem: load(p) for p in sorted(here.glob("P*.py"))}


def apply(engine_root, defect) -> None:
    target = pathlib.Path(engine_root) / defect.TARGET
    text = target.read_text(encoding="utf-8")
    if defect.OLD not in text:
        raise SystemExit(f"{defect.__name__}: anchor not found in {defect.TARGET}")
    target.write_text(text.replace(defect.OLD, defect.NEW, 1), encoding="utf-8")
