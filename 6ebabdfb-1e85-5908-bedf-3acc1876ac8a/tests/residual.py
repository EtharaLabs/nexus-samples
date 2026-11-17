"""The residual check: what a naive first-pass fuzzer reaches, and that no difference
it finds comes from anything other than the twelve planted defects.

Fairness is structural: `shipped` is `reference` with exactly the twelve patches and
nothing else, so every shipped-vs-reference difference is one planted defect or a
compound of several. A compound cannot become a valid finding, because reducing its
world isolates it to one defect. So this check reports two things: how many defects a
naive random world reaches through a difference one defect explains (the hardness
bound, target at most three), and how many random differences are compounds of two or
more planted defects (reducible, never a new defect).

The generator is a naive first-pass fuzzer: a short inheritance chain, never a
diamond; one to four statements; mostly `action` and `resource`; at most one
condition; ASCII values; fewer than nine statements. The twelve defects need structure
beyond this envelope, which is why designed experiments, not random worlds, find them.
"""

import json
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "tests" / "build"

SIMPLE_PATS = ["svc:*", "svc:read", "svc:read:*", "svc:*:all", "*", "svc:write"]
RESP = ["res", "res:1", "*", "res:*"]
OPS = ["equals", "equalsFold", "glob", "numLt", "anyOf", "allOf"]
SIMPLE_CTXV = ["bob", "alice", "admin", 5, 12, 0]


def world(r):
    depth = r.randint(1, 3)
    rn = [f"r{i}" for i in range(depth)]
    roles = {rn[0]: {}}
    for i in range(1, depth):
        roles[rn[i]] = {"inherits": [rn[i - 1]]}
    stmts = []
    for k in range(r.randint(1, 4)):
        s = {"id": f"s{k}", "effect": r.choice(["allow", "allow", "deny"])}
        if r.random() < 0.9:
            s["action"] = r.sample(SIMPLE_PATS, r.randint(1, 2))
        else:
            s["notAction"] = [r.choice(SIMPLE_PATS)]
        if r.random() < 0.9:
            s["resource"] = r.sample(RESP, r.randint(1, 2))
        else:
            s["notResource"] = r.sample(RESP[:3], r.randint(1, 2))
        if r.random() < 0.4:
            s["when"] = [
                {
                    "key": r.choice(["u", "n", "g"]),
                    "op": r.choice(OPS),
                    "values": r.sample(["bob", "admin", 10, 5], r.randint(1, 2)),
                }
            ]
        stmts.append(s)
    pols = []
    for i in range(r.randint(1, 2)):
        kk = r.randint(0, len(stmts))
        pols.append({"id": f"P{i}", "attach": r.choice(rn), "statements": stmts[:kk]})
        stmts = stmts[kk:]
    return {
        "roles": roles,
        "principals": {"p": {"roles": [r.choice(rn)]}},
        "policies": pols,
    }


def query(r):
    ctx = {k: r.choice(SIMPLE_CTXV) for k in ["u", "n", "g"] if r.random() < 0.7}
    return {
        "principal": "p",
        "action": r.choice(["svc:read", "svc:read:all", "svc:write", "other"]),
        "resource": r.choice(["res", "res:1", "other"]),
        "context": ctx,
    }


def run(tree, calls):
    code = (
        "import json,sys\n"
        + f"sys.path.insert(0,{str(tree)!r})\n"
        + "import ward\no=[]\n"
        "for v,w,q in json.load(open(sys.argv[1])):\n"
        "  try:o.append(ward.answer(v,w,q))\n"
        "  except ward.errors.WardError as e:o.append({'error':type(e).code})\n"
        "  except Exception as e:o.append({'crash':type(e).__name__})\n"
        "json.dump(o,open(sys.argv[2],'w'))\n"
    )
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "c").write_text(json.dumps(calls))
    (d / "r").write_text(code)
    res = subprocess.run(
        [sys.executable, str(d / "r"), str(d / "c"), str(d / "o")],
        capture_output=True,
        text=True,
    )
    if not (d / "o").exists():
        raise SystemExit("residual run failed: " + res.stderr[-400:])
    return json.loads((d / "o").read_text())


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    r = random.Random(11)
    calls = []
    for _ in range(n):
        w, q = world(r), query(r)
        calls.append(("decide", w, q))
        calls.append(("explain", w, q))
    shipped = run(BUILD / "shipped", calls)
    reference = run(BUILD / "reference", calls)
    variants = {p.name[2:]: run(p, calls) for p in sorted(BUILD.glob("M_*"))}

    reached, compound = {}, 0
    for i in range(len(calls)):
        if shipped[i] != reference[i]:
            owners = [k for k in variants if variants[k][i] == reference[i]]
            if len(owners) == 1:
                reached[owners[0]] = reached.get(owners[0], 0) + 1
            else:
                compound += 1
    print(f"residual check: {len(calls)} calls over {n} naive random worlds")
    for defect in sorted(variants):
        print(
            f"  {defect:28s} {'reached x' + str(reached[defect]) if defect in reached else 'not reached'}"
        )
    print(
        f"\ndefects a naive random world reaches: {len(reached)} (hardness target at most 3)"
    )
    print(f"compound differences (two or more planted defects, reducible): {compound}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
