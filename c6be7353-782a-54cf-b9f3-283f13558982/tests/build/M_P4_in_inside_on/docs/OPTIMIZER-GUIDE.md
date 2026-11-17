# tarn optimizer guide

> **What this guide is.** It records what the engine does, as observed by running it.
> Every plan below is the verbatim output of `conn.explain(sql)` and every result is
> `repr(conn.execute(sql).rows)`, both produced against `sample/sample.json`. The
> guide describes observed behaviour, not intended behaviour: `docs/DESIGN.md` is
> the specification, and wherever the two disagree, DESIGN.md is right.

**Running the examples.** From the application directory, `import tarn`, open the
sample with `conn = tarn.connect("sample/sample.json")`, and print
`conn.explain(sql)` for any query below. `explain()` plans a statement without
executing it, and leaves `conn.stats.rows_processed` at 0.

**Reading a plan.** Each line is one physical operator, indented two spaces deeper
than the operator that consumes it. An operator's inputs follow it in input order,
so the left (outer) input of a join comes first. The engine prints these labels:

- `SeqScan <table> AS <alias>` reads a table in storage order.
- `IndexScan <table> AS <alias> ON <column>` reads a table in the order of its
  index on that column.
- `Filter` keeps the rows for which its predicate is TRUE; FALSE and NULL both
  discard the row.
- `NestedLoopJoin kind=inner|left`, `HashJoin kind=inner|left` and
  `MergeJoin kind=inner` are the physical joins, chosen as described under
  Physical join selection.
- `AntiJoin` and `NullAwareAntiJoin` evaluate a rewritten `NOT IN`.
- `AntiMatch` emits the rows of its left input that have no partner in its right
  input under the join condition, `NullPad` sets the right-hand columns of every
  row it receives to NULL, and `UnionAll` concatenates its two inputs.
- `Sort`, `Limit` and `Project` implement `ORDER BY`, `LIMIT` and the select list.

**The rule pipeline.** Five rewrite rules run once each, always in this order:
`fold`, `notin`, `outer_join`, `pushdown`, `sortelim` (the order of
`tarn.plan.pipeline.RULE_NAMES`). Physical join selection then runs over the
rewritten plan. Setting `conn.disabled_rules` to a set of rule names, for example
`frozenset({"pushdown"})`, skips those rules, which is the quickest way to see what
one rule contributes to a plan.

**Counting work.** `conn.stats.rows_processed` counts the rows the operators
examined during the last `execute()`. Scans count the rows they read, `Filter`
counts the rows it tests, `Sort` counts the rows it sorts, and each join or
anti-join counts the rows or row pairs it examines. `Project`,
`Limit`, `NullPad` and `UnionAll` add nothing. A subquery that runs once per row
adds its own operators' counts every time it runs. The row budgets in
`bench/budgets.json` use this unit.

## fold

Constant folding replaces every subtree built only from literals, arithmetic,
comparisons, `AND`, `OR`, `NOT` and `COALESCE` with its value, computed once at
plan time by the same evaluator the executor uses, so the folded literal carries
the same three-valued result that row-by-row evaluation would have produced. It
rewrites the `WHERE`, `ON` and select-list expressions of the statement being
planned, but never the shape of the plan: below, the `Filter` compares `e.id` with
the literal 2 instead of dividing 10 by 4 for every row. A constant whose evaluation
raises, such as `1 / 0`, is left in place and raises only when a row reaches it.

```sql
SELECT e.id, e.mgr / 3 AS third
FROM emp e
WHERE e.id > 10 / 4
ORDER BY e.id
```

```text
Project
  Sort
    Filter
      SeqScan emp AS e
```

## notin

A `WHERE` conjunct `x NOT IN (SELECT col FROM t ...)` whose subquery selects one
bare column from a single table, with no join, `ORDER BY` or `LIMIT`, becomes an
anti-join: the outer input on the left, and on the right a scan of `t` under the
subquery's own `WHERE` as a `Filter`. When the subquery column is declared
`NOT NULL`, as `customers.id` is here, the plain `AntiJoin` is used; for
`NOT IN (SELECT m.mgr FROM emp m)`, whose column is nullable, the plan uses
`NullAwareAntiJoin` instead, which keeps no outer row once the subquery has
produced a NULL. Any other `NOT IN` in a `WHERE` clause, and every `IN` there,
stays in its `Filter` and runs the subquery again for each row.

```sql
SELECT e.id
FROM emp e
WHERE e.id NOT IN (SELECT c.id FROM customers c WHERE c.region = 'east')
ORDER BY e.id
```

```text
Project
  Sort
    AntiJoin
      SeqScan emp AS e
      Filter
        SeqScan customers AS c
```

## outer_join

The rule looks only at a `WHERE` clause that sits directly on a `LEFT JOIN`, and
only at the conjuncts that name a column of the right-hand, NULL-supplying table.
A conjunct that is never TRUE on a NULL-padded row, such as `t.status = 'open'`,
makes the padding pointless, so the join runs as an inner join and pushdown then
moves the conjunct onto the right-hand scan. The example below filters through
`COALESCE`; `docs/DESIGN.md` section 6.3 defines how the rule must treat a filter
like that, and the plan shows what the engine does with it.

```sql
SELECT c.id, t.id
FROM customers c
LEFT JOIN tickets t ON t.cust = c.id
WHERE COALESCE(t.status, 'none') <> 'shut'
ORDER BY c.id
```

```text
Project
  Sort
    UnionAll
      NestedLoopJoin kind=inner
        SeqScan customers AS c
        Filter
          Filter
            SeqScan tickets AS t
      Filter
        NullPad
          AntiMatch
            SeqScan customers AS c
            SeqScan tickets AS t
```

## pushdown

Pushdown splits a `WHERE` clause that sits on a join into its `AND`-ed conjuncts,
and moves each conjunct that names the columns of one input only into a `Filter`
directly above that input. A conjunct that names both inputs, or no column at all,
stays above the join. The right input of a `LEFT JOIN` never receives a conjunct,
because filtering it would change which left rows find a partner, but the left
input of either kind of join does.

```sql
SELECT e.id, d.label
FROM emp e
JOIN depts d ON d.code = e.dept
WHERE e.mgr = 10 AND d.label <> 'Beta'
ORDER BY e.id
```

```text
Project
  Sort
    NestedLoopJoin kind=inner
      Filter
        SeqScan emp AS e
      Filter
        SeqScan depts AS d
```

## sortelim

Sort elimination drops a `Sort` whose only key is an ascending bare column when
its input is a scan of that column's table, possibly under filters, and the table
has an index on the column with the same collation. The scan becomes an
`IndexScan` that delivers the rows in the index's order, so no sort runs at all. A
`DESC` key, a second key, an expression or a join below the `Sort` keeps the
`Sort`, and `docs/DESIGN.md` section 7 fixes the order in which an index stores its
keys.

```sql
SELECT e.id, e.mgr
FROM emp e
ORDER BY e.mgr
```

```text
Project
  IndexScan emp AS e ON mgr
```

## Physical join selection

After the rules have run, each join picks a physical operator. An inner join whose
`ON` clause is a single equality between a column of each input becomes a
`MergeJoin` when both inputs are bare scans of tables indexed on those columns and
the two columns share a type and a collation; both scans then become `IndexScan`s.
Otherwise an `ON` clause of that form gets a `HashJoin` when the right input is
estimated at 8 rows or more, and every other join runs as a `NestedLoopJoin`. No
sample table holds 8 rows, so the second join below, whose left input is itself a
join, falls back to a nested loop.

```sql
SELECT e.id, d.label, r.v
FROM emp e
JOIN rates r ON r.k = e.mgr
JOIN depts d ON d.code = e.dept
ORDER BY e.id, r.v
```

```text
Project
  Sort
    NestedLoopJoin kind=inner
      MergeJoin kind=inner
        IndexScan emp AS e ON mgr
        IndexScan rates AS r ON k
      SeqScan depts AS d
```

## Example outputs

The rows below are `repr(conn.execute(sql).rows)` for three of the queries above.
Each of them is answered by the engine's own operators; `docs/DESIGN.md` is the statement of what the rows should be.

```sql
SELECT e.id, d.label
FROM emp e
JOIN depts d ON d.code = e.dept
WHERE e.mgr = 10 AND d.label <> 'Beta'
ORDER BY e.id
```

```python
[[2, 'Alpha'], [5, 'Gamma']]
```

```sql
SELECT e.id
FROM emp e
WHERE e.id NOT IN (SELECT c.id FROM customers c WHERE c.region = 'east')
ORDER BY e.id
```

```python
[[1], [3], [4]]
```

```sql
SELECT e.id, e.mgr / 3 AS third
FROM emp e
WHERE e.id > 10 / 4
ORDER BY e.id
```

```python
[[3, 6], [4, None], [5, 3]]
```
