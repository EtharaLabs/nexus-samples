import os
import pathlib
import sys

ENGINE = pathlib.Path(os.environ["BB_ENGINE"])


def patch(rel: str, old: str, new: str, label: str) -> int:
    path = ENGINE / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        print(f"{label}: anchor not found in {rel}", file=sys.stderr)
        return 1
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: planted in {rel}")
    return 0
