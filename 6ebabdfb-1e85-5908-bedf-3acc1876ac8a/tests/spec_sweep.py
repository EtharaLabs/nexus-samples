"""The spec sweep: what a careful reader catches with one simple probe per rule.

For each numbered rule it runs the one to three simplest calls a reader would write
to see that rule work, over small worlds: single-path roles, fewer than nine
statements, ASCII values, present context keys, non-empty lists, numbers for numLt.
A defect the sweep catches is one the agent would find the same way, so the target is
that it catches at most two of the twelve.
"""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "tests" / "build"


def st(
    sid, eff, action=None, notAction=None, resource=None, notResource=None, when=None
):
    d = {"id": sid, "effect": eff}
    if action is not None:
        d["action"] = action
    if notAction is not None:
        d["notAction"] = notAction
    if resource is not None:
        d["resource"] = resource
    elif notResource is not None:
        d["notResource"] = notResource
    else:
        d["resource"] = ["*"]
    if when is not None:
        d["when"] = when
    return d


def W(stmts, roles=None, principals=None):
    return {
        "roles": roles or {"r": {}},
        "principals": principals or {"p": {"roles": ["r"]}},
        "policies": [{"id": "P", "attach": "r", "statements": stmts}],
    }


def Q(action="svc:read", resource="res", context=None):
    return {
        "principal": "p",
        "action": action,
        "resource": resource,
        "context": context or {},
    }


# one simple ordinary-case probe per rule
SWEEP = {
    "3 action glob": [
        ("decide", W([st("a", "allow", action=["svc:*"])]), Q(action="svc:read"))
    ],
    "3 ? matches one": [
        ("decide", W([st("a", "allow", action=["svc:rea?"])]), Q(action="svc:read")),
        ("decide", W([st("a", "allow", action=["svc:rea?"])]), Q(action="svc:readX")),
    ],
    "3 notResource": [
        (
            "decide",
            W([st("a", "allow", action=["svc:*"], notResource=["secret"])]),
            Q(resource="res"),
        )
    ],
    "4 equals": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "u", "op": "equals", "values": ["bob"]}],
                    )
                ]
            ),
            Q(context={"u": "bob"}),
        )
    ],
    "4 equalsFold": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "u", "op": "equalsFold", "values": ["BOB"]}],
                    )
                ]
            ),
            Q(context={"u": "bob"}),
        )
    ],
    "4 glob cond": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "u", "op": "glob", "values": ["b*"]}],
                    )
                ]
            ),
            Q(context={"u": "bob"}),
        )
    ],
    "4 numLt": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "n", "op": "numLt", "values": [10]}],
                    )
                ]
            ),
            Q(context={"n": 5}),
        ),
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "n", "op": "numLt", "values": [10]}],
                    )
                ]
            ),
            Q(context={"n": 20}),
        ),
    ],
    "4 anyOf": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "g", "op": "anyOf", "values": ["x"]}],
                    )
                ]
            ),
            Q(context={"g": ["x", "y"]}),
        )
    ],
    "4 allOf": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "g", "op": "allOf", "values": ["x", "y"]}],
                    )
                ]
            ),
            Q(context={"g": ["x"]}),
        )
    ],
    "5 inheritance": [],  # set below, with the policy on the inherited role
    "6 specificity": [
        (
            "decide",
            W(
                [
                    st("a", "allow", action=["svc:read:all"]),
                    st("d", "deny", action=["svc:read:*"]),
                ]
            ),
            Q(action="svc:read:all"),
        )
    ],
    "7 ordering": [
        ("decide", W([st("a", "allow", action=["svc:*"])]), Q(action="svc:read"))
    ],
    "8 scan": [
        (
            "decide",
            W([st(f"s{i}", "allow", action=[f"svc:{i}"]) for i in range(4)]),
            Q(action="svc:1"),
        )
    ],
    "9 explain": [
        ("explain", W([st("a", "allow", action=["svc:read"])]), Q(action="svc:read"))
    ],
    "10 errors": [
        (
            "decide",
            W(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "u", "op": "numLt", "values": [1]}],
                    )
                ]
            ),
            Q(context={"u": 0}),
        )
    ],
}
# the section-5 probe was written with its policy on the inherited role
SWEEP["5 inheritance"] = [
    (
        "decide",
        {
            "roles": {"r": {"inherits": ["base"]}, "base": {}},
            "principals": {"p": {"roles": ["r"]}},
            "policies": [
                {
                    "id": "P",
                    "attach": "base",
                    "statements": [st("a", "allow", action=["svc:*"])],
                }
            ],
        },
        Q(action="svc:read"),
    )
]


def run(tree, calls):
    import tempfile

    code = (
        "import json,sys\n"
        f"sys.path.insert(0,{str(tree)!r})\n"
        "import ward\no=[]\n"
        "for verb,w,q in json.load(open(sys.argv[1])):\n"
        "  try: o.append(ward.answer(verb,w,q))\n"
        "  except ward.errors.WardError as e: o.append({'error':type(e).code})\n"
        "  except Exception as e: o.append({'crash':type(e).__name__})\n"
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
        raise SystemExit("sweep run failed: " + res.stderr[-400:])
    return json.loads((d / "o").read_text())


def main() -> int:
    calls, index = [], []
    for rule, probes in SWEEP.items():
        for c in probes:
            index.append(rule)
            calls.append(c)
    shipped = run(BUILD / "shipped", calls)
    reference = run(BUILD / "reference", calls)
    variants = {p.name[2:]: run(p, calls) for p in sorted(BUILD.glob("M_*"))}

    caught = {}
    for i, rule in enumerate(index):
        if shipped[i] != reference[i]:
            owners = [k for k in variants if variants[k][i] == reference[i]]
            for o in owners:
                caught.setdefault(o, rule)
    print(f"spec sweep: {len(calls)} probes over {len(SWEEP)} rules")
    for defect in sorted(META := list(p.name[2:] for p in sorted(BUILD.glob("M_*")))):
        mark = f"CAUGHT at '{caught[defect]}'" if defect in caught else "missed"
        print(f"  {defect:26s} {mark}")
    print(f"\ndefects caught by the sweep: {len(caught)} (target at most 2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
