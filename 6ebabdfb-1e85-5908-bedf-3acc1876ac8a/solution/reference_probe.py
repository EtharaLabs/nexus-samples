"""The reference investigation: the calls a solver makes, and the findings they prove.

Each probe establishes the ordinary behaviour of a rule, shows one departure from it,
reproduces the departure, and bounds it with a one-element reduction. The nine probes
together name every defect. `plan()` is the ordered call list solve.sh replays; it is
what the budget has to cover.
"""

import json
import pathlib


def st(
    sid, effect, action=None, notAction=None, resource=None, notResource=None, when=None
):
    d = {"id": sid, "effect": effect}
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


def pol(pid, stmts, attach="r"):
    return {"id": pid, "attach": attach, "statements": stmts}


def simple(stmts, attach="r"):
    return {
        "roles": {"r": {}},
        "principals": {"p": {"roles": ["r"]}},
        "policies": [pol("P", stmts, attach)],
    }


def query(action="svc:read", resource="res", context=None, principal="p"):
    return {
        "principal": principal,
        "action": action,
        "resource": resource,
        "context": context or {},
    }


_FILLERS = [st(f"f{i}", "allow", action=[f"filler:{i}"]) for i in range(8)]
W_P1 = simple(_FILLERS + [st("q", "allow", action=["svc:rea?"])])
W_P2 = simple([st("a", "allow", action=["abc"]), st("b", "deny", action=["a**b**"])])
W_P3 = {
    "roles": {"r0": {"inherits": ["r1"]}, "r1": {}},
    "principals": {"p": {"roles": ["r0"]}},
    "policies": [
        pol("Pa", [st("sa", "allow", action=["svc:read"])], attach="r0"),
        pol("Pd", [st("sd", "deny", action=["svc:read"])], attach="r1"),
    ],
}
W_P4 = simple(
    [
        st(
            "a",
            "allow",
            action=["svc:*"],
            when=[{"key": "team", "op": "allOf", "values": ["x"]}],
        )
    ]
)
W_P5 = {
    "roles": {
        "top": {"inherits": ["base", "chainA"]},
        "chainA": {"inherits": ["chainB"]},
        "chainB": {"inherits": ["base"]},
        "base": {},
    },
    "principals": {"p": {"roles": ["top"]}},
    "policies": [
        pol("Pb", [st("s2", "allow", action=["svc:read"])], attach="base"),
        pol("Px", [st("s1", "allow", action=["svc:read"])], attach="chainB"),
    ],
}
W_P6 = simple(
    [
        st(
            "a",
            "allow",
            action=["svc:*"],
            when=[{"key": "u", "op": "equalsFold", "values": ["\u00c4dmin"]}],
        )
    ]
)
W_P7 = simple(
    [st("na", "deny", notAction=["xxxxxxxxxx"]), st("aa", "allow", action=["svc:read"])]
)
W_P8 = simple(
    [st("a", "allow", action=["svc:read"]), st("z", "allow", action=["svc:read"])]
)
W_P9 = simple(
    [
        st(
            "a",
            "allow",
            action=["svc:*"],
            when=[
                {"key": "u", "op": "equals", "values": ["x"]},
                {"key": "n", "op": "numLt", "values": [1]},
            ],
        )
    ]
)


def _eight():
    w = json.loads(json.dumps(W_P1))
    w["policies"][0]["statements"] = w["policies"][0]["statements"][:7] + [
        w["policies"][0]["statements"][8]
    ]
    return w


def _p5_without(pid):
    w = json.loads(json.dumps(W_P5))
    w["policies"] = [p for p in w["policies"] if p["id"] != pid]
    return w


def _p5_one_path():
    w = json.loads(json.dumps(W_P5))
    w["roles"]["chainB"]["inherits"] = []
    return w


def _p3_without(pid):
    w = json.loads(json.dumps(W_P3))
    w["policies"] = [p for p in w["policies"] if p["id"] != pid]
    return w


W_P10 = {
    "roles": {"r0": {"inherits": ["r1"]}, "r1": {}},
    "principals": {"p": {"roles": ["r0"]}},
    "policies": [
        pol(
            "Pa",
            [st(f"f{i}", "allow", action=[f"filler:{i}"]) for i in range(7)]
            + [st("saa", "allow", action=["svc:read"])],
            attach="r0",
        ),
        pol("Pz", [st("szz", "allow", action=["svc:read"])], attach="r1"),
    ],
}
W_P11 = simple(
    [
        st(
            "a",
            "allow",
            action=["svc:*"],
            when=[{"key": "n", "op": "numLt", "values": [9007199254740993]}],
        )
    ]
)
W_P12 = simple(
    [
        st(
            "a",
            "allow",
            action=["svc:*"],
            when=[{"key": "g", "op": "anyOf", "values": ["5"]}],
        )
    ]
)


def _p10_small():
    w = json.loads(json.dumps(W_P10))
    sts = w["policies"][0]["statements"]
    w["policies"][0]["statements"] = sts[:6] + sts[7:]
    return w


PROBES = {
    "P1_index_drops_qmark": {
        "section": "8",
        "kind": "answer",
        "world": W_P1,
        "query": query(),
        "expected": {"decision": "allow"},
        "observed": {"decision": "deny"},
        "rationale": "Section 8 says the action-index path must agree with the scanning path. "
        "With nine effective statements the index misses the statement whose action "
        "pattern holds a '?'.",
        "calls": [
            ("decide", _eight(), query()),
            ("decide", W_P1, query()),
            ("decide", W_P1, query(action="svc:reaX")),
        ],
        "boundary": ("decide", _eight(), query()),
    },
    "P2_specificity_length": {
        "section": "6",
        "kind": "answer",
        "world": W_P2,
        "query": query(action="abc"),
        "expected": {"decision": "allow"},
        "observed": {"decision": "deny"},
        "rationale": "Section 6 says action-specificity is the count of non-wildcard characters. "
        "The exact 'abc' allow must beat 'a**b**', a deny with fewer non-wildcard "
        "characters but the same length.",
        "calls": [
            ("decide", simple([st("a", "allow", action=["abc"])]), query(action="abc")),
            (
                "decide",
                simple([st("b", "deny", action=["a**b**"])]),
                query(action="abc"),
            ),
            ("decide", W_P2, query(action="abc")),
        ],
        "boundary": (
            "decide",
            simple([st("a", "allow", action=["abc"])]),
            query(action="abc"),
        ),
    },
    "P3_depth_before_effect": {
        "section": "6",
        "kind": "answer",
        "world": W_P3,
        "query": query(action="svc:read"),
        "expected": {"decision": "deny"},
        "observed": {"decision": "allow"},
        "rationale": "Section 6 orders effect before depth, so at equal specificity the deny at "
        "depth 1 beats the allow at depth 0.",
        "calls": [
            (
                "decide",
                simple([st("sa", "allow", action=["svc:read"])]),
                query(action="svc:read"),
            ),
            ("decide", W_P3, query(action="svc:read")),
            ("decide", _p3_without("Pd"), query(action="svc:read")),
        ],
        "boundary": ("decide", _p3_without("Pd"), query(action="svc:read")),
    },
    "P4_allof_not_vacuous": {
        "section": "4",
        "kind": "answer",
        "world": W_P4,
        "query": query(),
        "expected": {"decision": "allow"},
        "observed": {"decision": "deny"},
        "rationale": "Section 4 says allOf over a key the context does not hold is vacuously TRUE, "
        "so the statement applies when 'team' is absent.",
        "calls": [
            ("decide", W_P4, query(context={"team": "x"})),
            ("decide", W_P4, query()),
            ("decide", simple([st("a", "allow", action=["svc:*"])]), query()),
        ],
        "boundary": ("decide", simple([st("a", "allow", action=["svc:*"])]), query()),
    },
    "P5_closure_deepest": {
        "section": "5",
        "kind": "trace",
        "world": W_P5,
        "query": query(action="svc:read"),
        "expected": {"deciding": "s2"},
        "observed": {"deciding": "s1"},
        "rationale": "Section 5 records a role reached by two paths at its shallowest depth, so "
        "base at depth 1 beats chainB at depth 2 and s2 decides.",
        "calls": [
            (
                "explain",
                simple([st("s2", "allow", action=["svc:read"])]),
                query(action="svc:read"),
            ),
            ("explain", _p5_one_path(), query(action="svc:read")),
            ("explain", W_P5, query(action="svc:read")),
            ("explain", _p5_without("Pb"), query(action="svc:read")),
        ],
        "boundary": ("explain", _p5_without("Pb"), query(action="svc:read")),
    },
    "P6_fold_unicode": {
        "section": "4",
        "kind": "answer",
        "world": W_P6,
        "query": query(context={"u": "\u00e4dmin"}),
        "expected": {"decision": "deny"},
        "observed": {"decision": "allow"},
        "rationale": "Section 4 says equalsFold folds the ASCII letters A-Z only, so 'ädmin' and "
        "'Ädmin' stay distinct and the condition fails.",
        "calls": [
            ("decide", W_P6, query(context={"u": "\u00c4DMIN"})),
            ("decide", W_P6, query(context={"u": "admin"})),
            ("decide", W_P6, query(context={"u": "\u00e4dmin"})),
            ("decide", W_P6, query()),
            (
                "decide",
                simple([st("a", "allow", action=["svc:*"])]),
                query(context={"u": "\u00e4dmin"}),
            ),
        ],
        "boundary": ("decide", W_P6, query()),
    },
    "P7_notaction_specificity": {
        "section": "6",
        "kind": "answer",
        "world": W_P7,
        "query": query(action="svc:read"),
        "expected": {"decision": "allow"},
        "observed": {"decision": "deny"},
        "rationale": "Section 6 says a notAction statement has action-specificity 0, so the specific "
        "action allow beats the notAction deny.",
        "calls": [
            (
                "decide",
                simple([st("aa", "allow", action=["svc:read"])]),
                query(action="svc:read"),
            ),
            (
                "decide",
                simple(
                    [
                        st("na", "deny", notAction=["x"]),
                        st("aa", "allow", action=["svc:read"]),
                    ]
                ),
                query(action="svc:read"),
            ),
            ("decide", W_P7, query(action="svc:read")),
            (
                "decide",
                simple([st("na", "deny", notAction=["xxxxxxxxxx"])]),
                query(action="svc:read"),
            ),
        ],
        "boundary": (
            "decide",
            simple([st("na", "deny", notAction=["xxxxxxxxxx"])]),
            query(action="svc:read"),
        ),
    },
    "P8_explain_tiebreak": {
        "section": "9",
        "kind": "trace",
        "world": W_P8,
        "query": query(action="svc:read"),
        "expected": {"deciding": "a"},
        "observed": {"deciding": "z"},
        "rationale": "Section 9 with the section 6 id tie-break: among equal matches that share an "
        "effect the deciding id is the smallest, 'a'.",
        "calls": [
            ("decide", W_P8, query(action="svc:read")),
            ("explain", W_P8, query(action="svc:read")),
            (
                "explain",
                simple([st("a", "allow", action=["svc:read"])]),
                query(action="svc:read"),
            ),
        ],
        "boundary": (
            "explain",
            simple([st("a", "allow", action=["svc:read"])]),
            query(action="svc:read"),
        ),
    },
    "P9_condition_short_circuit": {
        "section": "4",
        "kind": "error",
        "world": W_P9,
        "query": query(context={"n": "notnum"}),
        "expected": {"error": "WARD-203"},
        "observed": {"decision": "deny"},
        "rationale": "Section 4 says every condition is evaluated and an error propagates, so the "
        "numLt on a non-number raises WARD-203 even though the first condition, an equals "
        "on an absent key, is FALSE.",
        "calls": [
            ("decide", W_P9, query(context={"u": "x", "n": 0})),
            ("decide", W_P9, query(context={"n": "notnum"})),
            (
                "decide",
                simple(
                    [
                        st(
                            "a",
                            "allow",
                            action=["svc:*"],
                            when=[{"key": "n", "op": "numLt", "values": [1]}],
                        )
                    ]
                ),
                query(context={"n": "notnum"}),
            ),
            ("decide", W_P9, query()),
        ],
        "boundary": (
            "decide",
            simple(
                [
                    st(
                        "a",
                        "allow",
                        action=["svc:*"],
                        when=[{"key": "n", "op": "numLt", "values": [1]}],
                    )
                ]
            ),
            query(context={"n": "notnum"}),
        ),
    },
    "P10_index_dedup_trace": {
        "section": "8",
        "kind": "trace",
        "world": W_P10,
        "query": query(action="svc:read"),
        "expected": {"deciding": "saa"},
        "observed": {"deciding": "szz"},
        "rationale": "Section 8 says the action-index path must agree with the scanning path. "
        "With nine statements the index keeps only the last statement for the exact action "
        "'svc:read', so it drops 'saa' at depth 0 and explain names 'szz' at depth 1.",
        "calls": [
            ("explain", _p10_small(), query(action="svc:read")),
            ("explain", W_P10, query(action="svc:read")),
            ("decide", W_P10, query(action="svc:read")),
        ],
        "boundary": ("explain", _p10_small(), query(action="svc:read")),
    },
    "P11_numlt_float": {
        "section": "4",
        "kind": "answer",
        "world": W_P11,
        "query": query(context={"n": 9007199254740992}),
        "expected": {"decision": "allow"},
        "observed": {"decision": "deny"},
        "rationale": "Section 4 says numLt compares exactly, so 9007199254740992 is less than "
        "9007199254740993 even though both are nearest the same float; converting to float "
        "first makes them equal and the allow is lost.",
        "calls": [
            ("decide", W_P11, query(context={"n": 0})),
            ("decide", W_P11, query(context={"n": 9007199254740992})),
            (
                "decide",
                simple([st("a", "allow", action=["svc:*"])]),
                query(context={"n": 9007199254740992}),
            ),
            ("decide", W_P11, query()),
        ],
        "boundary": (
            "decide",
            simple([st("a", "allow", action=["svc:*"])]),
            query(context={"n": 9007199254740992}),
        ),
    },
    "P12_anyof_stringify": {
        "section": "4",
        "kind": "answer",
        "world": W_P12,
        "query": query(context={"g": 5}),
        "expected": {"decision": "deny"},
        "observed": {"decision": "allow"},
        "rationale": "Section 4 says anyOf equality is by exact value and kind, so the number 5 does "
        "not equal the string '5'; comparing by text form makes the condition hold and allows.",
        "calls": [
            ("decide", W_P12, query(context={"g": "5"})),
            ("decide", W_P12, query(context={"g": 5})),
            (
                "decide",
                simple([st("a", "allow", action=["svc:*"])]),
                query(context={"g": 5}),
            ),
            ("decide", W_P12, query()),
        ],
        "boundary": (
            "decide",
            simple([st("a", "allow", action=["svc:*"])]),
            query(context={"g": 5}),
        ),
    },
}


ORIENTATION = [
    ("decide", simple([st("o1", "allow", action=["svc:*"])]), query()),
    ("decide", simple([st("o1", "deny", action=["svc:*"])]), query()),
    (
        "decide",
        {"roles": {"r": {}}, "principals": {"p": {"roles": ["r"]}}, "policies": []},
        query(),
    ),
    ("explain", simple([st("o1", "allow", action=["svc:*"])]), query()),
    (
        "explain",
        {"roles": {"r": {}}, "principals": {"p": {"roles": ["r"]}}, "policies": []},
        query(),
    ),
]


def findings():
    return [
        {
            "section": p["section"],
            "kind": p["kind"],
            "input": p["world"],
            "request": p["query"],
            "expected": p["expected"],
            "observed": p["observed"],
            "rationale": p["rationale"],
        }
        for p in PROBES.values()
    ]


def plan():
    calls = list(ORIENTATION)
    for p in PROBES.values():
        calls += p["calls"]
        verb = "explain" if p["kind"] == "trace" else "decide"
        calls.append((verb, p["world"], p["query"]))
        calls.append(p["boundary"])
    return calls


def main() -> int:
    out = pathlib.Path(__file__).resolve().parent / "findings.json"
    out.write_text(json.dumps(findings(), indent=2) + "\n", encoding="utf-8")
    calls = plan()
    print(f"reference findings: {len(findings())} -> {out.name}")
    print(
        f"reference call count: {len(calls)} "
        f"({len(ORIENTATION)} orientation, {sum(len(p['calls']) for p in PROBES.values())} probes, "
        f"{2 * len(PROBES)} reproduction and boundary)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
