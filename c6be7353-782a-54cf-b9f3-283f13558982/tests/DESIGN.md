# tarn design

This document is the specification of the `tarn` engine. Where the code and this document disagree, this document is right.

## 1. Scope

`tarn` answers single-statement `SELECT` queries over an in-memory catalog loaded from JSON. It has a lexer, a parser, a binder, a rule-based optimizer, and a row-based executor. This document is the only statement of what an answer must be. The engine ships no second evaluator to compare against, so a claim about correct behaviour is settled here and not by another implementation.

## 2. The SQL subset

```
select      := SELECT select_list FROM table_ref join_clause* [WHERE expr]
               [ORDER BY order_item (',' order_item)*] [LIMIT integer]
join_clause := [INNER | LEFT] JOIN table_ref ON expr
select_list := '*' | select_item (',' select_item)*
select_item := expr [AS identifier]
order_item  := expr [ASC | DESC]
table_ref   := identifier [[AS] identifier]
expr        := expr OR expr | expr AND expr | NOT expr
             | expr ('=' | '<>' | '<' | '<=' | '>' | '>=') expr
             | expr IS [NOT] NULL
             | expr IS NOT DISTINCT FROM expr
             | expr [NOT] LIKE expr
             | expr [NOT] IN '(' select ')'
             | expr ('+' | '-' | '*' | '/') expr
             | COALESCE '(' expr (',' expr)+ ')'
             | CASE (WHEN expr THEN expr)+ [ELSE expr] END
             | '-' expr | '(' expr ')' | literal | column_ref
```

`IN` and `NOT IN` compare against the first column their subquery selects; any further column the subquery selects is ignored. A subquery sees only the tables it names itself, so a reference from inside it to a table alias of the enclosing query is `TARN-200`, and an unqualified name that only the enclosing query defines is `TARN-201`: correlated subqueries are outside this subset, and so are aggregates, `GROUP BY`, `HAVING`, `UNION` and `DISTINCT`.

`- e` means `0 - e`. Parentheses only group: `(e)` is the expression `e` itself everywhere in this document.

## 3. Values, types and comparison

The value kinds are `INTEGER`, `REAL`, `TEXT`, `BOOLEAN` and the absent value `NULL`. A column declares one of the four kinds and whether it is nullable.

- `INTEGER` and `REAL` compare exactly and across kinds: `1 = 1.0` is TRUE. No comparison converts an `INTEGER` to a `REAL` first, so two values that differ by less than one unit in the last place of a `REAL` are still different values. `2` raised to the 53rd power plus 1 is not equal to the `REAL` nearest it.
- `TEXT` compares under its collation (section 5).
- `BOOLEAN` compares only with `BOOLEAN`, and `FALSE` orders before `TRUE`. `TRUE` is never equal to `1`.
- Comparing `TEXT` with a numeric kind, or `BOOLEAN` with any other kind, is rejected at bind time as `TARN-203`.
- Arithmetic is defined on `INTEGER` and `REAL` operands only: an arithmetic operator with a `TEXT` or a `BOOLEAN` operand is rejected at bind time as `TARN-203`.
- Arithmetic propagates `NULL`: if either operand is `NULL` the result is `NULL`, for division too, so `NULL / 0` is `NULL`.
- `INTEGER / INTEGER` truncates toward zero, so `-7 / 2` is `-3`. If either operand is `REAL` the result is `REAL`. Division by zero raises `TARN-301`.
- The arguments of a `COALESCE`, and the branch results of a `CASE` together with its `ELSE` result, must share one kind, `NULL` aside and with `INTEGER` and `REAL` counting as one kind here; otherwise the expression is rejected at bind time as `TARN-203`. The kind they share is the kind of the whole expression wherever this section checks kinds.

## 4. Three-valued logic

A predicate evaluates to TRUE, FALSE or NULL. `WHERE` and `ON` keep a row only when the predicate is exactly TRUE.

| `a` | `b` | `a AND b` | `a OR b` |
|---|---|---|---|
| TRUE | TRUE | TRUE | TRUE |
| TRUE | FALSE | FALSE | TRUE |
| TRUE | NULL | NULL | TRUE |
| FALSE | FALSE | FALSE | FALSE |
| FALSE | NULL | FALSE | NULL |
| NULL | NULL | NULL | NULL |

`NOT TRUE` is FALSE, `NOT FALSE` is TRUE, `NOT NULL` is NULL.

`AND` and `OR` evaluate both of their operands; neither one short-circuits. An error raised while evaluating either operand is raised by the whole expression, so `1 = 2 AND x / 0 > 1` raises `TARN-301` rather than evaluating to FALSE. `CASE` and `COALESCE` are the exceptions. `CASE` evaluates its conditions in order and stops at the first one that is TRUE, then evaluates that branch's result and no other, or the `ELSE` result when no condition is TRUE. `COALESCE` evaluates its arguments in order and stops at the first one that is not `NULL`, so `COALESCE(1, x / 0)` is 1 while `COALESCE(x / 0, 1)` raises `TARN-301`. Any comparison with a `NULL` operand is NULL. `x IS NULL` and `x IS NOT NULL` are always TRUE or FALSE, never NULL. `a IS NOT DISTINCT FROM b` is TRUE when both are `NULL`, FALSE when exactly one is, and otherwise the result of `a = b`; it is never NULL.

`COALESCE` returns its first argument that is not `NULL`, or `NULL` if every argument is. `CASE` returns the result of its first branch whose condition is exactly TRUE, otherwise the `ELSE` result, otherwise `NULL`.

### 4.1 IN and NOT IN

Let `S` be the multiset of values the subquery returns.

| case | `x IN (S)` | `x NOT IN (S)` |
|---|---|---|
| `S` is empty | FALSE | TRUE, for every `x`, `NULL` included |
| some element equals `x` | TRUE | FALSE |
| no element equals `x`, and `S` holds no `NULL` | FALSE | TRUE |
| no element equals `x`, and `S` holds a `NULL` | NULL | NULL |
| `x` is `NULL` and `S` is not empty | NULL | NULL |

## 5. Collation

A `TEXT` column declares `BINARY` (the default) or `NOCASE`.

- `BINARY` compares code point by code point.
- `NOCASE` folds each of the twenty-six ASCII letters `A` to `Z` to its lower-case form before comparing, so the fold is downward and `'_'` sorts before `'A'` under `NOCASE`. No other character is folded: `É` and `é` stay distinct under `NOCASE`, and so do `ß` and `SS`.

The collation of a comparison is the collation of its left operand when that operand carries one, otherwise the collation of its right operand, otherwise `BINARY`.

What an operand carries is fixed as follows. A column reference carries the collation its column declares, so a column declared `BINARY` carries `BINARY`. A literal carries none. `COALESCE` carries the collation of the first of its arguments that carries one, and none when no argument does. `CASE` carries the collation of the first of its branch results that carries one, taking the `ELSE` result last, and none when no result does. Every other expression carries none.

A column reference carries its declared collation wherever it is written, including inside the subquery of an `IN` or a `NOT IN`. Resolving a name in an inner scope never changes the collation of the column it names.

For `IN` and `NOT IN` the comparison is between the left operand and the first column the subquery selects, and its collation follows the rule above with that column as the right operand.

`LIKE` is a comparison and honours the collation of its left operand under the same rule. In a pattern, `%` matches any run of zero or more characters and `_` matches exactly one; every other character matches itself. `x LIKE NULL` and `NULL LIKE p` are NULL.

## 6. The optimizer

The optimizer applies the rules below, once each, in this order: `fold`, `notin`, `outer_join`, `pushdown`, `sortelim`. Every rule is semantics preserving on its own, so disabling any subset of the rules must not change the answer to any query, only its plan and its cost. A rule fires wherever its documented precondition holds.

### 6.1 Shared analyses

`expr_columns(e)` is the set of column references `e` contains.

`strict_in(e, S)` holds when `e` evaluates to `NULL` whenever every column in `S` is `NULL`. It is defined inductively:

- a column reference is strict in `S` exactly when it is a member of `S`;
- a literal is strict in `S` exactly when the literal is `NULL`;
- a comparison, an arithmetic operator, and `LIKE` are strict in `S` when either operand is;
- `COALESCE(a1, ..., an)` is strict in `S` only when every argument is;
- `AND`, `OR`, `NOT`, `IS NULL`, `IS NOT NULL`, `IS NOT DISTINCT FROM` and `CASE` are not strict in `S`.

`null_rejecting(e, S)` holds when `e` cannot evaluate to TRUE once every column in `S` is `NULL`. It is defined inductively:

- `a AND b` is null-rejecting when `a` is or `b` is;
- `a OR b` is null-rejecting when `a` is and `b` is;
- a comparison or a `LIKE` is null-rejecting when either operand is strict in `S`;
- a bare `BOOLEAN` column reference is null-rejecting when it is a member of `S`;
- `x IS NOT NULL` is null-rejecting when `x` is strict in `S`;
- `x IS NULL`, `IS NOT DISTINCT FROM`, `NOT`, `CASE` and `COALESCE` as a whole predicate are not null-rejecting.

So `COALESCE(t.x, 0) = 0` is not null-rejecting for `{t.x}` while `t.x = 0` is, and `t.x IS NULL` is not while `t.x IS NOT NULL` is.

`not_null_columns(p, C)` is the subset of candidate columns `C` that a predicate `p` proves non-`NULL` for every row it keeps: a candidate is proven when some `AND`-conjunct of `p` is null-rejecting for that single column.

### 6.2 fold

A subtree whose every leaf is a literal is replaced by the literal it evaluates to, under the three-valued rules of section 4. Folding never changes a result, so `x = NULL` folds to `NULL` and never to FALSE.

### 6.3 outer_join

Let `L LEFT JOIN R ON c` carry a `WHERE` predicate `p`, and let `N` be the columns of `R`. Consider the `AND`-conjuncts of `p` that reference a column of `N`.

- If there are none, the join is unchanged.
- If any such conjunct is null-rejecting for `N`, no row with a `NULL`-padded right side can survive `p`, so the join becomes an `INNER` join.
- Otherwise the join is rewritten as the union of two legs, the null-tolerant split:
  - the inner leg is `L INNER JOIN R ON c` filtered by `p`, and conjuncts of `p` that reference only columns of `N` may be pushed onto `R` in this leg;
  - the anti-join leg is the rows of `L` that have no partner in `R` as it stands, unfiltered, padded with `NULL` for every column of `N`, then filtered by `p`.

The test for the inner-join conversion applies to each `LEFT` join that lies beneath the `WHERE`, and not only to the join the `WHERE` sits directly above. For each such join, the conjuncts of `p` that reference columns of that join's null-supplying side decide whether it becomes an `INNER` join, independently of every other join. In `A LEFT JOIN B ON cb LEFT JOIN C ON cc WHERE p`, a conjunct of `p` that is null-rejecting for the columns of `B` makes the join with `B` an `INNER` join whatever `p` says about `C`. The null-tolerant split applies to the `LEFT` join the `WHERE` sits directly above.

  The anti-join leg must read the unfiltered `R`. A left row whose partners all exist but all fail `p` is not an unmatched row and must not appear padded.

### 6.4 notin

`x NOT IN (SELECT y FROM r [WHERE q])` becomes an anti-join of the enclosing input against `r` on `x = y`.

The anti-join must implement the full section 4.1 table whenever `y` can be `NULL`, that is whenever `y` is declared nullable and `not_null_columns(q, {y})` does not prove it non-`NULL`.

When `y` cannot be `NULL` the anti-join may skip the step that checks whether `S` holds a `NULL`, because it cannot. It may skip nothing else. In particular a `NULL` `x` is still treated as section 4.1 requires: against a non-empty `S` the result is `NULL` and the row does not survive, and against an empty `S` the result is TRUE and the row does survive, whether or not `y` is nullable.

### 6.5 pushdown

An `AND`-conjunct of a `WHERE` predicate that references columns of one join input only is moved onto that input. For a `LEFT` join only the preserved side may receive a conjunct this way; the null-supplying side may not, because a conjunct that is not null-rejecting would then turn matched rows into padded rows.

### 6.6 sortelim

A single `ORDER BY` key that is a bare column reference in `ASC` direction is satisfied by an index on that column when the index collation equals the key collation. The `Sort` is then dropped and the scan reads through the index. A `DESC` key, a key over an expression, and a second key are not eliminated by this rule.

## 7. Ordering

`ORDER BY ... ASC` places `NULL` before every non-`NULL` value. `DESC` compares in the opposite direction on its key, so it places `NULL` last.

An `ORDER BY` key is an expression over the columns of the tables the statement names, in its `FROM` and in its joins. A name introduced by `AS` in the select list is not in scope there, so ordering by such a name is `TARN-201`. An integer literal in an `ORDER BY` key is an ordinary constant and never a column position, so it orders every row alike.

Sorting is stable, and stability is not reversed by `DESC`: rows that compare equal on a key keep their relative input order whichever direction that key is sorted in. Keys are applied left to right, and rows equal on every key keep their relative input order.

An index stores its table's rows in `ASC` order of the index column under the column's collation, with the same `NULL` placement. Reading through an index therefore yields exactly `ORDER BY column ASC`.

## 8. Physical operators

The join implementation is chosen from input size and available index order only. Whether the two key columns declare the same kind decides nothing about the hash join and the nested loop join: a hash join is chosen for an INTEGER key against a REAL key exactly as it would be for two INTEGER keys. The merge join alone carries a kind condition, stated below, because it walks two indexes in step and two indexes over different kinds are not in step.

Three further terms are fixed here. An equality join between two bare column references is a join whose whole `ON` predicate is one comparison `x = y`, with `x` a column reference to one of its inputs and `y` a column reference to the other, written in either order; a join whose `ON` carries any other conjunct is not one. The build side of a hash join is its right input. The number of rows an input holds, for the threshold below, is the number of rows the catalog stores for that base table, counted before any filter is applied to it.

- A merge join is chosen for an equality join between two bare column references when both inputs are base-table scans carrying an index on their key column, the two keys share a declared kind, and they share a collation. Both inputs are then read through those indexes. Because a `NULL` key is equal to nothing, a merge join skips `NULL` keys on either side and continues; it must not stop when it meets one.
- Otherwise a hash join is chosen for an equality join between two bare column references when the build side holds at least 8 rows. Two keys that compare equal under section 3 must land in one bucket and two that do not must not.
- Otherwise a nested loop join is used.

`rows_processed`, which `execute` and `explain` report, counts the rows every operator examined while answering the statement.

## 9. EXPLAIN

A plan fixes, for each join in the statement, which join operator answers it and that operator's kind. Nothing else about the text a plan renders is specified here: the placement of other operators, the rendering of a subquery, and the spelling of an identifier may be read in more than one way, and no claim about correct behaviour may rest on them.

The join tree is built left-deep in the order the `FROM` clause names its tables, and joins are never reordered. `Project` is the outermost operator of a plan, `Limit` sits directly beneath it when the statement carries one, and `Sort` beneath that. A statement whose select list is `*` carries a `Project` like any other. The plan of a subquery is not rendered.

`explain` renders the chosen physical plan as one line per operator, two spaces of indentation per level, children in input order. Operator lines are `SeqScan <table> AS <alias>`, `IndexScan <table> AS <alias> ON <column>`, `NestedLoopJoin kind=<inner|left>`, `HashJoin kind=<inner|left>`, `MergeJoin kind=inner`, `AntiJoin`, `NullAwareAntiJoin`, `AntiMatch`, `NullPad`, `UnionAll`, `Filter`, `Sort`, `Limit` and `Project`.

## 10. Error codes

| code | raised when |
|---|---|
| `TARN-101` | the statement does not parse |
| `TARN-200` | a table or table alias does not exist |
| `TARN-201` | a column does not exist |
| `TARN-202` | an unqualified column is ambiguous, or a table alias repeats (a name given by `AS` in a select list may repeat) |
| `TARN-203` | a comparison or an expression mixes kinds section 3 forbids |
| `TARN-301` | division by zero |
