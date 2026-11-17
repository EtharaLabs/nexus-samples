`tarn` is a small relational engine. You cannot see its source. It runs as a service on the network, and the only way to reach it is the client `tarn-cli`.

`docs/DESIGN.md` is the engine's specification. It defines every value and comparison, the collation rules, the three-valued logic including the `IN` and `NOT IN` table, the ordering, the precondition of every optimizer rule, the physical operator choice, and the error codes. It is complete and it is the only authority: where the engine departs from it, the engine is wrong.

**The engine has exactly seven defects.** Each one breaks a rule written in `docs/DESIGN.md`. Find all seven and report them.

## Reaching the engine

```
tarn-cli execute --db sample/sample.json --sql "SELECT c.id FROM customers c"
tarn-cli explain --db sample/sample.json --sql "SELECT c.id FROM customers c"
tarn-cli budget
```

A database is a JSON file shaped like `sample/sample.json`; write your own files and pass them with `--db`, or pass `-` to read one from standard input. `execute` prints the rows, `explain` prints the plan the engine chose. Both print `rows_processed` and the calls you have left on standard error. `budget` costs nothing.

- **Each `execute` and each `explain` spends one call, and the service allows 250 in all.** When they are gone every further call is refused with `TARN-429` and nothing more can be learned, so spend them on experiments you have a reason to run.
- **A database must be valid.** It has a non-empty `tables` object. Every table has a non-empty `columns` list and a `rows` list. Every column has a `name`, a `type` among `INTEGER`, `REAL`, `TEXT` and `BOOLEAN`, an optional `collation` (`BINARY` or `NOCASE`, on `TEXT` columns only) and an optional `nullable` (`true` unless given). Every row holds exactly one value per column, each of its column's kind (a `REAL` column also takes a whole number) or `null` where the column is nullable. The optional `indexes` list names each index, one table, and one column of that table. Names are identifiers, and no two tables, no two columns of one table and no two indexes share a name, ignoring case. The service refuses a database that is not valid with `TARN-400`, says why, and spends no call.
- A statement that breaks a rule of the specification comes back with the `TARN` code section 10 gives it, and its message.
- A failure inside the engine itself comes back as `TARN-000` with a fixed message and nothing else. It carries no detail about where or why. `TARN-000` means the engine fell over, which is itself worth knowing.
- `rows_processed` is a diagnostic only. `docs/DESIGN.md` does not define it exactly, so **no finding may rest on it.**
- **The service logs every call** with its verb, its statement, its outcome, and a digest of its database. That log is the record of your investigation; the Reproduced and Bounded conditions below are about what it holds. The digest depends on every key and every value of the database and on nothing else: the same JSON with its keys in another order or laid out differently has the same digest, but `1` and `1.0` give different digests, and so do a `nullable` written out and the same `nullable` left to its default.

## What counts as a defect

A finding must show a difference from `docs/DESIGN.md` in one of three things:

- **`answer`**: the rows a statement returns.
- **`plan`**: for some join in the statement, which join operator answers it or that operator's kind. A plan specifies only that much, as section 9 says, so a plan finding must turn on a join's operator or its kind and on nothing else about the plan's text.
- **`error`**: the `TARN` code a statement raises, including a statement that raises where the specification requires rows, or returns rows where it requires a code.

A report can also be mistaken. Some of what the specification requires looks wrong by convention, and it is still what the engine must do. Reporting such behaviour as a defect is a false finding, and one false finding makes the whole report wrong, so check a surprising result against `docs/DESIGN.md` before you report it.

## Deliverable

Write `/app/out/findings.json`: a JSON list of exactly seven objects, one per defect.

```json
[
  {
    "section": "4.1",
    "kind": "answer",
    "database": {"tables": {"t": {"columns": [{"name": "x", "type": "INTEGER"}], "rows": [[1]]}}, "indexes": []},
    "sql": "SELECT t.x FROM t t WHERE t.x = 1"
  }
]
```

- `section`: the numbered section of `docs/DESIGN.md` whose rule the engine breaks, as a string, for example `"5"` or `"6.3"`. Where the rule a defect breaks is stated in more than one section, you may cite any of those sections.
- `kind`: one of `"answer"`, `"plan"`, `"error"`.
- `database`: the database itself, inline and valid, so that the finding reproduces on its own.
- `sql`: one statement that shows the defect.

The entry above is an illustration of the shape only. It names no defect.

Every finding must also meet three conditions.

**Minimal.** Taking away any one of the following must leave a case that no longer shows the defect:

- one row of a table;
- one column of a table, with its values and any index on it;
- one table, with its indexes;
- one index;
- one item of a select list that has more than one;
- one `AND`-conjunct of a `WHERE` or of an `ON`, or the whole `WHERE` when it has a single conjunct (parentheses only group, so `(a AND b) AND c` has the three conjuncts `a`, `b` and `c`);
- one join, with its `ON`;
- one `ORDER BY` key, or the whole `ORDER BY` when it has a single key;
- the `LIMIT`.

The same holds inside every subquery, for its select list, joins, `WHERE`, `ORDER BY` and `LIMIT`. A case no longer shows the defect when the engine follows the specification on it, when it departs in a way some other defect explains, or when it no longer runs. A table may have no rows at all when the defect does not need any.

**Reproduced.** The call log must hold the finding's own statement, spacing and keyword case aside, run on the finding's own database (the same digest), with `explain` for a `plan` finding and `execute` for an `answer` or `error` finding. Send the `database` you report, not a copy you changed afterwards.

**Bounded.** The call log must also hold at least one case made from the finding by taking away exactly one of the elements listed under Minimal and changing nothing else, run with the same verb. It shows where the defect stops.

## What the report needs

The report is complete only when all of these hold:

- each of the seven defects is shown by one finding: run on its own database, the finding's statement shows a difference that exactly one of the seven explains, and the finding cites that defect's section and an observable the difference appears in. A finding that cites a real defect with the wrong section or the wrong kind does not show it;
- every finding is minimal in its rows;
- every finding is minimal in its tables, columns and indexes;
- every finding is minimal in its statement;
- every finding is reproduced in the call log;
- every finding is bounded in the call log.

Any one of these makes the whole report wrong, whatever the other findings show: a finding that shows no difference at all, a finding that no single defect explains, a finding that reports behaviour the specification requires, a finding whose database is not valid, more than seven entries, and a call refused because the budget was spent.

## How to run the investigation

Work so that `findings.json` and the call log also show each of the following. Points 1 to 5, 9 and 11 restate requirements above.

1. Every finding's statement runs on its own database: every table and column it names is declared there.
2. No finding's statement holds a join, a conjunct, an `ORDER BY` key, a `LIMIT` or a select item without a role in its defect.
3. No two findings report the same behaviour.
4. No finding's database holds a table, column, row or index without a role in its defect.
5. The call log shows the findings' statements were run before they were reported.
6. The call log reads as experiments: series of related calls that vary one feature at a time.
7. The call log holds at least one call showing the ordinary case of a rule beside the call showing its departure.
8. No statement is sent unchanged with the same database more than twice.
9. No finding rests on `rows_processed`.
10. No finding reports a behaviour the specification leaves open, such as plan text beyond each join's operator and kind, or the name of an unaliased select expression.
11. Every finding's `kind` names an observable its own statement can show.
12. The call log holds at least one `explain`.
13. Every `TARN-000` in the call log is followed later by a call on the same database whose statement differs from the failing one in one respect only.
14. For every `error` finding, the call log holds a call made after the finding's own statement was run, whose statement is the finding's own, unchanged or with one element taken away or changed, and whose outcome is not that error.
