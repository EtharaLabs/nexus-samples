"""Command line front end.

python3 -m tarn.cli --db sample/sample.json --sql "SELECT c.id FROM customers c"
python3 -m tarn.cli --db sample/sample.json --sql "..." --explain
"""
import argparse
import json
import sys

from . import api
from .types import TarnError


def render_rows(result) -> str:
    lines = []
    if result.columns:
        lines.append(" | ".join(result.columns))
        lines.append("-" * len(lines[0]))
    for row in result.rows:
        lines.append(" | ".join("NULL" if cell is None else str(cell) for cell in row))
    lines.append(f"({len(result.rows)} row{'' if len(result.rows) == 1 else 's'})")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tarn.cli")
    parser.add_argument("--db", required=True, help="path to a JSON database")
    parser.add_argument("--sql", required=True, help="the statement to run")
    parser.add_argument("--explain", action="store_true", help="print the plan instead")
    parser.add_argument(
        "--stats", action="store_true", help="also print rows processed"
    )
    parser.add_argument("--json", action="store_true", help="print rows as JSON")
    parser.add_argument(
        "--disable",
        action="append",
        default=[],
        metavar="RULE",
        help="switch off one optimizer rule; may be repeated",
    )
    args = parser.parse_args(argv)

    try:
        conn = api.connect(args.db)
        if args.disable:
            conn.disabled_rules = frozenset(args.disable)
        if args.explain:
            print(conn.explain(args.sql))
        else:
            result = conn.execute(args.sql)
            if args.json:
                print(json.dumps({"columns": result.columns, "rows": result.rows}))
            else:
                print(render_rows(result))
        if args.stats:
            print(f"rows_processed: {conn.stats.rows_processed}")
    except TarnError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"no such database: {args.db}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
