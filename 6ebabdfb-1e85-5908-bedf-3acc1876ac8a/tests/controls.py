"""Controls on the grader: what each kind of submission scores.

The reference findings score 1.0; an empty submission 0; a single finding well under
1.0; and each false submission zeroes the compiled score, whatever else it holds: a
finding that shows no difference, a decoy the specification requires, an invalid
world, more than twelve entries, and a spent budget.
"""

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRADE = ROOT / "tests" / "grade.py"
sys.path.insert(0, str(ROOT / "solution"))
sys.path.insert(0, str(ROOT / "tests"))
import reference_probe as rp  # noqa: E402
import wardshape  # noqa: E402

REF = rp.findings()


def _log(calls):
    return "\n".join(
        json.dumps(
            {
                "call": i,
                "verb": v,
                "world_digest": wardshape.world_digest(w),
                "query": q,
                "outcome": "ok",
            }
        )
        for i, (v, w, q) in enumerate(calls, 1)
    )


REF_LOG = _log(rp.plan())


def score(findings, log_text=REF_LOG, budget=240):
    work = pathlib.Path(tempfile.mkdtemp(prefix="ctl-"))
    (work / "f.json").write_text(json.dumps(findings))
    (work / "log").write_text(log_text)
    done = subprocess.run(
        [
            sys.executable,
            str(GRADE),
            "--findings",
            str(work / "f.json"),
            "--build",
            str(ROOT / "tests" / "build"),
            "--log",
            str(work / "log"),
            "--budget",
            str(budget),
            "--out",
            str(work / "g.json"),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if not (work / "g.json").exists():
        return None
    return json.loads((work / "g.json").read_text())


def main() -> int:
    cases = {}
    cases["reference (all twelve)"] = REF
    cases["empty"] = []
    cases["one finding only"] = REF[:1]
    # A true decoy: a more specific allow beats a less specific deny, which the
    # specification requires and the engine does correctly, so there is no difference.
    decoy = dict(REF[0])
    decoy["section"] = "6"
    decoy["kind"] = "answer"
    decoy["input"] = {
        "roles": {"r": {}},
        "principals": {"p": {"roles": ["r"]}},
        "policies": [
            {
                "id": "P",
                "attach": "r",
                "statements": [
                    {
                        "id": "a",
                        "effect": "allow",
                        "action": ["svc:read:all"],
                        "resource": ["*"],
                    },
                    {
                        "id": "d",
                        "effect": "deny",
                        "action": ["svc:*"],
                        "resource": ["*"],
                    },
                ],
            }
        ],
    }
    decoy["request"] = {
        "principal": "p",
        "action": "svc:read:all",
        "resource": "res",
        "context": {},
    }
    decoy["expected"] = {"decision": "deny"}
    decoy["observed"] = {"decision": "allow"}
    cases["reports a decoy (specificity)"] = REF[:8] + [decoy]
    invalid = dict(REF[1])
    invalid["input"] = {"roles": {}}
    cases["invalid world"] = REF[:8] + [invalid]
    cases["thirteen entries"] = REF + [REF[0]]

    print(f"{'control':34s} {'compiled':>9s} {'gate_ok':>8s}  items")
    for label, findings in cases.items():
        r = score(findings)
        if r is None:
            print(f"{label:34s} grade failed")
            continue
        passed = sum(1 for v in r["items"].values() if v >= 1.0)
        print(
            f"{label:34s} {r['compiled']:>9.4f} {str(r['gate']['ok']):>8s}  {passed}/{len(r['items'])}"
        )

    over = rp.plan() + [("decide", rp.W_P1, rp.query())] * 240
    r = score(
        REF,
        _log(over)
        + "\n"
        + json.dumps({"call": 999, "verb": "decide", "refused": True}),
        budget=240,
    )
    print(
        f"{'budget spent':34s} {r['compiled']:>9.4f} {str(r['gate']['ok']):>8s}  "
        f"{sum(1 for v in r['items'].values() if v >= 1.0)}/{len(r['items'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
