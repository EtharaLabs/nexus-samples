"""Attribute each finding to exactly one defect.

A finding belongs to defect k when the shipped engine and the reference differ on it
in some observable, and the shipped engine with only k repaired agrees with the
reference in every observable. A finding attributed to none, or to more than one, is
false: the first shows nothing, the second needs two repairs to disappear.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from spec_sweep import BUILD, differs, run  # noqa: E402

OBSERVABLE = {"answer": "answer", "plan": "plan", "error": "answer"}


def attribute(findings: list) -> list:
    cases = [(f"f{i}", entry["sql"]) for i, entry in enumerate(findings)]
    dbs = {f"f{i}": entry["database"] for i, entry in enumerate(findings)}
    out = []
    for i, entry in enumerate(findings):
        name = f"f{i}"
        single = [(name, entry["sql"])]
        import spec_sweep

        saved = spec_sweep.DB
        spec_sweep.DB = dbs[name]
        try:
            shipped = run(BUILD / "shipped", single)[name]
            reference = run(BUILD / "reference", single)[name]
            kinds = differs(shipped, reference)
            owners = []
            if kinds:
                for variant in sorted(BUILD.glob("M_*")):
                    if not differs(run(variant, single)[name], reference):
                        owners.append(variant.name[2:])
        finally:
            spec_sweep.DB = saved
        out.append({"index": i, "section": entry["section"], "kind": entry["kind"],
                    "observed": kinds, "owners": owners})
    return out


def main() -> int:
    path = ROOT / "solution" / "findings.json"
    findings = json.loads(path.read_text(encoding="utf-8"))
    rows = attribute(findings)
    print(f"{'#':>2} {'section':>8} {'claimed':>7} {'observed':<24} owners")
    ok = True
    for row in rows:
        owners = ", ".join(o.split("_")[0] for o in row["owners"]) or "NONE"
        if len(row["owners"]) != 1:
            ok = False
        print(f"{row['index']:>2} {row['section']:>8} {row['kind']:>7} "
              f"{','.join(row['observed']) or '-':<24} {owners}")
    print(f"\nevery finding attributed to exactly one defect: {ok}")
    claimed = {o.split("_")[0] for r in rows for o in r["owners"]}
    print(f"distinct defects covered: {len(claimed)} of 7 -> {sorted(claimed)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
