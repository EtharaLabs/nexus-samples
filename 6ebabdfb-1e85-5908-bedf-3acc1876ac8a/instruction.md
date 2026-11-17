`ward` is an access-policy decision engine. You cannot see its source. It runs as a service on the network, and the only way to reach it is the client `ward-cli`.

`docs/SPEC.md` is the engine's specification. It defines every value and shape, the pattern matching, the condition operators, the role closure and inheritance depth, the precedence that selects the deciding statement, the decision, the fast paths and their preconditions, what `explain` reports, and the error codes. It is complete and it is the only authority: where the engine departs from it, the engine is wrong. `ward` resembles a cloud access-policy evaluator, but it differs from the well-known ones in several places `docs/SPEC.md` states; prior knowledge of those systems misleads, and the specification decides.

**The engine has exactly twelve defects.** Each one breaks a rule written in `docs/SPEC.md`. Find all twelve and report them.

## Reaching the engine

```
ward-cli decide  --world world.json --query query.json
ward-cli explain --world world.json --query '{"principal":"p","action":"a","resource":"r"}'
ward-cli budget
```

A world is a JSON file shaped like `sample/sample.json`; write your own files and pass them with `--world`, or pass `-` to read one from standard input. A query is a JSON file or an inline JSON string. `decide` prints the decision; `explain` prints the id of the statement that decided. Both print the calls you have left on standard error. `budget` costs nothing.

- **Each `decide` and each `explain` spends one call, and the service allows 240 in all.** When they are gone every further call is refused with `WARD-429` and nothing more can be learned, so spend them on experiments you have a reason to run.
- **A call must be valid.** The world has a non-empty set of roles, principals and policies in the shape `docs/SPEC.md` section 2 defines, and the query names a principal, an action and a resource. The service refuses an invalid call with `WARD-400`, says why, and spends no call.
- A call that breaks a rule of the specification comes back with the `WARD` code section 10 gives it, and its message.
- A failure inside the engine itself comes back as `WARD-000` with a fixed message and nothing else. It carries no detail about where or why. `WARD-000` means the engine fell over, which is itself worth knowing.
- **The service logs every call** with its verb, its query, its outcome, and a digest of its world. That log is the record of your investigation; the Reproduced and Bounded conditions below are about what it holds. The digest depends on every key and every value of the world and on nothing else: the same world with its keys in another order has the same digest, but `1` and `1.0` give different digests, and so do a field written out and the same field left to its default.

## What counts as a defect

A finding must show a difference from `docs/SPEC.md` in one of three things:

- **`answer`**: the decision `decide` returns.
- **`trace`**: the deciding-statement id `explain` returns. The specification fixes only that much of a trace, so a `trace` finding must turn on the deciding-statement id and nothing else.
- **`error`**: the `WARD` code a call raises, including a call that raises where the specification requires a decision, or returns a decision where it requires a code.

A report can also be mistaken. Some of what the specification requires looks wrong by convention, and it is still what the engine must do. Reporting such behaviour as a defect is a false finding, and one false finding makes the whole report wrong, so check a surprising result against `docs/SPEC.md` before you report it.

## Deliverable

Write `out/findings.json`, in the `out/` directory beside `docs/` and `sample/`: a JSON list of exactly twelve objects, one per defect.

```json
[
  {
    "section": "6",
    "kind": "answer",
    "input": {"roles": {"r": {}}, "principals": {"p": {"roles": ["r"]}}, "policies": [{"id": "P", "attach": "r", "statements": [{"id": "s", "effect": "allow", "action": ["a"], "resource": ["*"]}]}]},
    "request": {"principal": "p", "action": "a", "resource": "x", "context": {}},
    "expected": {"decision": "allow"},
    "observed": {"decision": "deny"},
    "rationale": "one or two sentences naming the broken rule"
  }
]
```

- `section`: the numbered section of `docs/SPEC.md` whose rule the engine breaks, as a string, for example `"5"` or `"6"`.
- `kind`: one of `"answer"`, `"trace"`, `"error"`.
- `input`: the world itself, inline and valid, so that the finding reproduces on its own.
- `request`: the query itself, inline and valid.
- `expected`: the output the specification requires, on the specified part only: `{"decision": ...}` for `answer`, `{"deciding": ...}` for `trace`, `{"error": "WARD-xxx"}` for `error`.
- `observed`: the output the engine actually gave, in the same shape.
- `rationale`: one or two sentences naming the broken rule and the sentence of its section.

The entry above is an illustration of the shape only. It names no defect.

Every finding must also meet three conditions.

**Minimal.** Taking away any one of the following must leave a case that no longer shows the defect: one role; one inheritance edge; one principal; one role of a principal; one policy; one statement; one pattern of an `action`, `notAction`, `resource` or `notResource` list that has more than one; one condition; one `values` entry of a condition that has more than one; one context key; one context value of a key that holds a list of more than one. The same holds for the query. A case no longer shows the defect when the engine follows the specification on it, when it departs in a way some other defect explains, or when it no longer runs. A policy may hold no statements and a context may be empty when the defect does not need them.

**Reproduced.** The call log must hold the finding's own query, run on the finding's own world (the same digest), with `explain` for a `trace` finding and `decide` for an `answer` or `error` finding. Send the `input` and `request` you report, not a copy you changed afterwards.

**Bounded.** The call log must also hold at least one case made from the finding by taking away exactly one of the elements listed under Minimal and changing nothing else, run with the same verb. Where a finding is reducible on both its world and its query, the log holds one reduction of each.

## What the report needs

Each of the twelve defects must be shown by exactly one finding: a finding whose query, run on its own world, shows a difference from `docs/SPEC.md` that repairing that defect alone would remove, and that cites the defect's section and an observable the difference appears in. The report is complete only when all twelve defects are shown this way and every finding meets the Minimal, Reproduced and Bounded conditions above and gives a correct `expected` and `observed`.

Any one of these makes the whole report wrong, whatever the other findings show: a finding that shows no difference, a finding that no single defect explains, a finding that reports behaviour the specification requires, a finding whose world or query is not valid, more than twelve entries, and a spent call budget.

## How to run the investigation

Work so that `findings.json` and the call log also show each of the following. Points 1 to 5 and 10 restate requirements above.

1. Every finding's query runs on its own world: every principal, role, action, resource and key it turns on is declared there.
2. No finding's world holds a role, inheritance edge, policy, statement or condition without a part in its defect.
3. No two findings report the same behaviour.
4. No finding's world holds a role, principal, policy, statement or condition without a part in its defect.
5. The call log shows the findings' queries were run before they were reported.
6. The call log reads as experiments: series of related calls that vary one feature at a time.
7. No call is sent unchanged, same verb and same world digest and query, more than twice.
8. No finding rests on anything `docs/SPEC.md` leaves undefined.
9. No finding reports a behaviour the specification leaves open, such as anything about a trace beyond the deciding-statement id.
10. Every finding's `kind` names an observable its own query can show.
11. The call log holds at least one `explain`.
12. Every `WARD-000` in the log is followed later by a call on the same world whose query differs from the failing one in one respect only.
13. For every `error` finding, the log holds a later call that is the finding's own query, unchanged or with one element taken away or changed, whose outcome is not that error.
14. Every finding's rationale names a specific sentence of the cited section, not the section number alone.
