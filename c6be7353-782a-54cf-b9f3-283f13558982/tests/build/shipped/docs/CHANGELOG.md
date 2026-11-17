# Changelog

All notable changes to tarn are recorded in this file, newest release first.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and tarn follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While
the major version is 0, a minor release may change behaviour.

## [0.8.0] - 2026-11-20

### Fixed

- A report built on `LEFT JOIN` no longer loses the rows that have no partner when the filter tolerates a missing side, such as a comparison wrapped in `COALESCE` or `CASE`, and the `WHERE column IS NULL` form of an anti-join keeps working.
- A `LEFT JOIN` whose filter tolerates a missing side no longer reports a row as unmatched when it does have partners and every one of them fails the filter.
- `ORDER BY` on a column that carries an index now places the rows with no value first, which is where `ORDER BY` on a column without an index already placed them.
- A join between two indexed columns that both hold empty values no longer returns an empty answer.
- `LIKE` on a column declared `COLLATE NOCASE` now matches regardless of the case of the ASCII letters, while leaving every other letter alone.

## [0.7.0] - 2026-09-29

### Added

- `Connection.explain(sql)` returns the physical plan as text, one operator per line, without running the statement.
- `conn.stats.rows_processed` reports how many rows the operators examined during the most recent `execute()`.
- `Connection.disabled_rules` switches individual optimizer rules off by name.
- `docs/OPTIMIZER-GUIDE.md`, a walk through the optimizer rules with the plans they produce.

### Fixed

- A constant division by zero such as `1 / 0` no longer fails while the statement is being planned; it raises `TARN-301` when a row reaches it.

## [0.6.0] - 2026-07-14

### Added

- Sort elimination: an ascending `ORDER BY` on a single indexed column reads the rows through the index instead of sorting them.
- `MergeJoin` for inner joins on an equality between two indexed columns.
- `IS NOT DISTINCT FROM`.

### Fixed

- A hash join now matches an `INTEGER` key with an equal `REAL` key, so `1` finds `1.0`.

## [0.5.0] - 2026-04-28

### Added

- A `NOT IN` subquery in a `WHERE` clause that selects one column from a single table, without `ORDER BY` or `LIMIT`, is planned as an anti-join instead of running the subquery again for every row.
- Every engine error now starts with a `TARN-` code, for example `TARN-201: no such column salary`.

### Changed

- Integer division truncates toward zero, so `-7 / 2` is `-3`, not `-4`.

## [0.4.0] - 2026-02-10

### Added

- `LEFT JOIN`, `COALESCE` and searched `CASE`.
- Predicate pushdown and constant folding.
- Sorted single-column indexes, declared under `indexes` in the database file.
