# ward specification

This document specifies the `ward` decision engine. Where the engine and this document disagree, this document is right. It is the only authority: the engine ships no second implementation, so a claim about correct behaviour is settled here.

`ward` resembles a cloud access-policy evaluator, but it is not one, and it differs from the well-known ones in several places stated below. Prior knowledge of those systems misleads; this document decides.

## 1. Scope

A call gives the engine a `world` and a `query`. The world holds roles, principals and policies. The query names a principal, an action, a resource and a context. The verb `decide` returns a decision; the verb `explain` returns the id of the statement that decided. The engine is deterministic: the same world and query always give the same result.

## 2. Shapes

A `world` is an object with three members. `roles` maps a role name to an object whose optional `inherits` is a list of role names. `principals` maps a principal name to an object whose `roles` is a list of role names. `policies` is a list of objects, each with a string `id`, a string `attach` naming one role, and a list `statements`.

A `statement` has a string `id`, an `effect` of `allow` or `deny`, exactly one of `action` or `notAction` (each a list of patterns), exactly one of `resource` or `notResource` (each a list of patterns), and an optional `when` (a list of conditions). A `condition` is an object `{key, op, values}` where `key` is a string, `op` names an operator of section 4, and `values` is a list.

A `query` is an object with a string `principal`, a string `action`, a string `resource`, and an optional `context` object. A context value is a scalar (string, number or boolean) or a list of scalars.

A name is an identifier: a non-empty string of letters, digits, and the characters `_ . : - /`. Policy ids are unique across the world, and so are statement ids. A world or query that breaks a rule of this section is invalid; the service refuses an invalid call with `WARD-400` and spends no call.

## 3. Matching

A pattern matches a string left to right. `*` matches any run of characters, the empty run included. `?` matches exactly one character and never the empty string. Every other character matches only itself, and matching is case sensitive.

A statement's action matches the query when: with `action`, some pattern in the list matches the query action; with `notAction`, no pattern in the list matches it. Resource matching is the same over `resource` and `notResource`. An empty `notResource` excludes nothing, so it matches every resource, and an empty `notAction` matches every action. An empty `action` or `resource` list matches nothing.

(Unlike the well-known evaluators, action and resource matching is case sensitive; `Read` and `read` are different actions.)

## 4. Conditions

A statement with a `when` list applies only when every condition in the list holds; the list is joined with `AND`. Every condition in the list is evaluated; an error raised while evaluating any condition is the statement's error, whether or not an earlier condition is FALSE. A condition reads its `key` from the query context. A key may be absent, may hold one scalar, or may hold a list of scalars.

The scalar operators are `equals`, `equalsFold`, `glob` and `numLt`. A scalar operator on an absent key is FALSE. A scalar operator on a key that holds a list is `WARD-203`. On a key that holds one scalar, the operator holds when the scalar relates to some element of `values`:

- `equals`: the context string equals the listed string exactly.
- `equalsFold`: `equals` after folding each of the twenty-six ASCII letters `A` to `Z` to its lower-case form, and no other character. `É` and `é` stay distinct, and so do `ß` and `SS`.
- `glob`: the context string is matched by the listed pattern under section 3.
- `numLt`: the context number is strictly less than the listed number. A context value that is not a number is `WARD-203`. Equal numbers do not satisfy `numLt`. The comparison is exact: a large integer is not converted to a floating-point number first, so `9007199254740992` is less than `9007199254740993` even though both are nearest the same float.

A scalar operator other than `numLt` on a context value that is not a string is `WARD-203`.

The set operators are `anyOf` and `allOf`, each reading every element the key holds (none when the key is absent). `anyOf` holds when some element the key holds equals some element of `values`; over an empty `values` list it is FALSE. An element equals a listed value only when the two have the same kind and the same value, so the number `5` does not equal the string `"5"`. `allOf` holds when every element the key holds is among `values`; over a key that holds no elements it is vacuously TRUE.

(Unlike the well-known evaluators, `allOf` over an absent key is TRUE, not FALSE.)

## 5. Role closure

A principal's effective roles are its own roles, at depth 0, together with every role reachable by following `inherits`. A role reached along several paths is recorded at its shallowest depth. A role's depth is used only to break ties in section 6.

A policy's statements are effective for a principal when the policy's `attach` role is one of the principal's effective roles; each such statement carries the depth of that role.

A reference to a role that the world does not define is `WARD-210`. A cycle in the inheritance graph, where a role inherits itself directly or through others, is `WARD-220`.

## 6. The deciding statement

Among the statements effective for the principal, a statement is a match when its action matches, its resource matches, and its conditions hold. The deciding statement is the first match in this order:

1. action-specificity, descending. A statement's action-specificity is the number of non-wildcard characters, those that are neither `*` nor `?`, in its most specific action pattern that matches the query action. A statement written with `notAction` has action-specificity 0.
2. effect, with `deny` before `allow`.
3. depth, ascending.
4. statement id, ascending.

(Unlike the well-known evaluators, `deny` does not always win. A more specific `allow` beats a less specific `deny`. `deny` beats `allow` only when the two matches have the same action-specificity.)

## 7. The decision

`decide` returns `{"decision": <effect>}`, the effect of the deciding statement. When no statement matches, the decision is `deny`.

## 8. Fast paths

When a principal has nine or more effective statements and none of them is written with `notAction`, the engine evaluates the action step through an action-index rather than by scanning every statement. The index path must agree with the scanning path on every query: it is an optimisation and changes no decision. Below nine effective statements, or when any effective statement uses `notAction`, the engine scans.

The engine may also cache a condition's result and short-circuit a match once the deciding statement is fixed; neither changes a decision.

## 9. explain

`explain` returns `{"deciding": <id>}`, the id of the deciding statement, or `{"deciding": null}` when no statement matches. The id of the deciding statement is the only thing `explain` specifies; it reports nothing else.

## 10. Error codes

| code | raised when |
|---|---|
| `WARD-203` | a condition applies an operator to a value of the wrong kind, as section 4 states |
| `WARD-210` | the query names a principal the world does not define, or a role reference does not resolve |
| `WARD-211` | a condition names an operator this document does not define |
| `WARD-220` | the inheritance graph holds a cycle |
| `WARD-400` | the world or the query is invalid under section 2 (service level; spends no call) |
| `WARD-000` | the engine failed; the message carries no detail |
