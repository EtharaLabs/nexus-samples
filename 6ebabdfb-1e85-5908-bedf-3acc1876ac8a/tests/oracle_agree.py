"""Independent-implementation agreement: the reference engine must match oracle.py.

oracle.py reimplements sections 3 to 9 sharing only wardshape, so agreement over many
random worlds is evidence the reference is correct and every shipped-vs-reference
difference is a planted defect, not a reference bug. The generator leans on the shapes
the twelve defects need (large integers, number-against-string contexts, nine or more
statements, inheritance diamonds) so the new rules are exercised, not skipped.
"""

import json
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "tests" / "build"
sys.path.insert(0, str(ROOT / "tests"))
import wardshape  # noqa: E402

ACTIONS = ["svc:read", "svc:read:all", "svc:*", "svc:rea?", "abc", "a*b", "*"]
KEYS = ["u", "n", "g", "team"]
SCALAR = ["admin", "Admin", "5", "x", 5, 5.0, 9007199254740992, 9007199254740993, True]
OPS = ["equals", "equalsFold", "glob", "numLt", "anyOf", "allOf"]


def _cond(rng):
    op = rng.choice(OPS)
    key = rng.choice(KEYS)
    if op in ("anyOf", "allOf"):
        vals = rng.choice([["5", "x"], [5, 6], ["admin"], []])
    elif op == "numLt":
        vals = [rng.choice([1, 5, 9007199254740993, 10**18])]
    else:
        vals = [rng.choice(["admin", "Admin", "5", "x"])]
    return {"key": key, "op": op, "values": vals}


def _statement(rng, i):
    st = {"id": f"s{i}", "effect": rng.choice(["allow", "deny"])}
    if rng.random() < 0.8:
        st["action"] = [rng.choice(ACTIONS)]
    else:
        st["notAction"] = [rng.choice(ACTIONS)]
    st["resource"] = ["*"]
    if rng.random() < 0.5:
        st["when"] = [_cond(rng) for _ in range(rng.randint(1, 2))]
    return st


def _world(rng):
    names = ["r0", "r1", "r2", "r3"]
    roles = {}
    for j, nm in enumerate(names):
        inh = [names[k] for k in range(j + 1, len(names)) if rng.random() < 0.5]
        roles[nm] = {"inherits": inh} if inh else {}
    n = rng.randint(1, 11)
    stmts = [_statement(rng, i) for i in range(n)]
    cut = rng.randint(0, n)
    policies = [
        {"id": "Pa", "attach": "r0", "statements": stmts[:cut] or [stmts[0]]},
        {
            "id": "Pb",
            "attach": rng.choice(names),
            "statements": stmts[cut:] or [stmts[-1]],
        },
    ]
    return {
        "roles": roles,
        "principals": {"p": {"roles": ["r0"]}},
        "policies": policies,
    }


def _query(rng):
    ctx = {}
    for key in KEYS:
        if rng.random() < 0.5:
            v = rng.choice(SCALAR)
            ctx[key] = [v, rng.choice(SCALAR)] if rng.random() < 0.3 else v
    return {
        "principal": "p",
        "action": rng.choice(ACTIONS),
        "resource": "res",
        "context": ctx,
    }


def _cases(seed, n):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        w, q = _world(rng), _query(rng)
        try:
            wardshape.validate_world(w)
            wardshape.validate_query(q)
        except wardshape.InvalidInput:
            continue
        out.append((rng.choice(["decide", "explain"]), w, q))
    return out


RUNNER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import {mod} as impl
out = []
for verb, w, q in json.load(open(sys.argv[2])):
    try:
        out.append(["ok", impl.answer(verb, w, q)])
    except Exception as exc:
        out.append(["err", getattr(exc, "code", type(exc).__name__)])
json.dump(out, open(sys.argv[3], "w"))
"""


def _run(path, mod, cases):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "r.py").write_text(RUNNER.format(mod=mod))
    (d / "c.json").write_text(json.dumps(cases))
    subprocess.run(
        [
            sys.executable,
            str(d / "r.py"),
            str(path),
            str(d / "c.json"),
            str(d / "o.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads((d / "o.json").read_text())


def main() -> int:
    cases = _cases(20240611, 800)
    ref = _run(BUILD / "reference", "ward", cases)
    ora = _run(ROOT / "tests", "oracle", cases)
    disagree = [i for i in range(len(cases)) if ref[i] != ora[i]]
    print(f"oracle vs reference: {len(cases) - len(disagree)}/{len(cases)} agree")
    for i in disagree[:8]:
        print(f"  case {i}: ref={json.dumps(ref[i])} oracle={json.dumps(ora[i])}")
        print(f"           {json.dumps(cases[i][0])} {json.dumps(cases[i][2])}")
    return 0 if not disagree else 1


if __name__ == "__main__":
    raise SystemExit(main())
