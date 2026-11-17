"""The grader.

Each finding is re-run against the shipped engine, the reference, and the shipped
engine with one defect repaired. A finding belongs to defect k when shipped and
reference differ on it and repairing only k removes the difference. A finding is
credited when exactly one defect owns it and the finding cites that defect's section
and an observable the difference appears in. Around the per-defect credit sit the
minimality, reproduction and boundary checks, and the expected/observed checks. A
false finding zeroes every item.
"""

import argparse
import copy
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reduce as reducer  # noqa: E402
import wardshape  # noqa: E402

# The sections whose rule each defect breaks; citing any one of them is credited. P1's
# index path stops matching `?` as one character (section 3) and so disagrees with the
# scanning path (section 8). P8 reverses the statement-id tie-break of section 6 and so
# reports the wrong deciding id (section 9). P9 evaluates conditions lazily against
# section 4, and its short-circuit changes the outcome, which section 8 forbids. P10's
# index path drops a statement (section 8), so the statement section 6 orders first is
# not the one that decides or that explain reports (section 9).
META = {
    "P1_index_drops_qmark": ("8", "3"),
    "P2_specificity_length": ("6",),
    "P3_depth_before_effect": ("6",),
    "P4_allof_not_vacuous": ("4",),
    "P5_closure_deepest": ("5",),
    "P6_fold_unicode": ("4",),
    "P7_notaction_specificity": ("6",),
    "P8_explain_tiebreak": ("9", "6"),
    "P9_condition_short_circuit": ("4", "8"),
    "P10_index_dedup_trace": ("8", "9", "6"),
    "P11_numlt_float": ("4",),
    "P12_anyof_stringify": ("4",),
}
EXPECTED = len(META)
VERB = {"answer": "decide", "error": "decide", "trace": "explain"}
STRUCTURE = (
    "role:",
    "inherit:",
    "principal:",
    "principal-role:",
    "policy:",
    "statement:",
    "condition:",
)
DATA = ("pattern:", "value:")
REQUEST = ("context-key:", "context-value:")

RUNNER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import ward
out = []
for verb, world, query in json.load(open(sys.argv[2])):
    try:
        out.append(ward.answer(verb, world, query))
    except ward.errors.WardError as exc:
        out.append({"error": type(exc).code})
    except Exception as exc:
        out.append({"error": "WARD-000"})
json.dump(out, open(sys.argv[3], "w"))
"""


def run(tree, calls):
    work = pathlib.Path(tempfile.mkdtemp(prefix="grade-"))
    (work / "r.py").write_text(RUNNER)
    (work / "c.json").write_text(json.dumps(calls))
    res = subprocess.run(
        [
            sys.executable,
            str(work / "r.py"),
            str(tree),
            str(work / "c.json"),
            str(work / "o.json"),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if not (work / "o.json").exists():
        raise SystemExit(f"engine run failed for {tree}: {res.stderr[-400:]}")
    return json.loads((work / "o.json").read_text())


def load_findings(path):
    if not path.exists():
        return [], ["findings.json is missing"]
    try:
        body = json.loads(path.read_text())
    except Exception as exc:
        return [], [f"findings.json does not parse: {exc}"]
    if not isinstance(body, list):
        return [], ["findings.json is not a list"]
    problems, clean = [], []
    for i, e in enumerate(body):
        if not isinstance(e, dict) or any(
            k not in e
            for k in ("section", "kind", "input", "request", "expected", "observed")
        ):
            problems.append(f"entry {i} is missing a required field")
            continue
        if not isinstance(e["kind"], str) or e["kind"] not in VERB:
            problems.append(f"entry {i} has an unknown kind {e['kind']!r}")
            continue
        try:
            wardshape.validate_world(e["input"])
            wardshape.validate_query(e["request"])
        except Exception as exc:  # InvalidInput, or a malformed shape
            problems.append(f"entry {i} input is invalid: {exc}")
            continue
        clean.append(e)
    return clean, problems


def load_log(path):
    if not path or not pathlib.Path(path).exists():
        return []
    out = []
    for line in pathlib.Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--build", default=str(HERE / "build"))
    ap.add_argument("--log", default="")
    ap.add_argument("--budget", type=int, default=240)
    ap.add_argument("--judge-dir", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    build = pathlib.Path(args.build)
    findings, problems = load_findings(pathlib.Path(args.findings))
    log = load_log(args.log)
    report = {"items": {}, "gate": {}, "findings": []}

    used = max([e.get("call", 0) for e in log] + [0])
    refused = sum(1 for e in log if e.get("refused"))
    report["gate"]["calls_used"] = used

    false_claims = list(problems)
    if len(findings) > EXPECTED:
        false_claims.append(f"{len(findings)} entries; at most {EXPECTED} allowed")
    if refused or used > args.budget:
        false_claims.append("the call budget was spent")

    # stage the judge inputs
    if args.judge_dir:
        jd = pathlib.Path(args.judge_dir)
        jd.mkdir(parents=True, exist_ok=True)
        (jd / "findings.json").write_text(json.dumps(findings, indent=2))
        (jd / "calls.jsonl").write_text("\n".join(json.dumps(e) for e in log))
        spec = HERE / "SPEC.md"
        if spec.exists():
            (jd / "SPEC.md").write_text(spec.read_text())

    variants = {p.name[2:]: p for p in sorted(build.glob("M_*"))}
    credited = {}
    owners = []
    if findings:
        calls = [(VERB[e["kind"]], e["input"], e["request"]) for e in findings]
        shipped = run(build / "shipped", calls)
        reference = run(build / "reference", calls)
        var_out = {k: run(v, calls) for k, v in variants.items()}
        for i, e in enumerate(findings):
            s, r = shipped[i], reference[i]
            seen = s != r
            own = [k for k in variants if var_out[k][i] == r] if seen else []
            rec = {
                "index": i,
                "section": str(e["section"]),
                "kind": e["kind"],
                "seen": seen,
                "owners": own,
            }
            owners.append(own[0] if len(own) == 1 else None)
            if not seen:
                false_claims.append(f"entry {i} shows no difference")
            elif len(own) != 1:
                false_claims.append(
                    f"entry {i} is explained by {len(own)} defects, not one"
                )
            else:
                section_ok = str(e["section"]).strip() in META[own[0]]
                kind_ok = _kind_shows(e["kind"], s, r)
                if section_ok and kind_ok:
                    rec["verdict"] = "credited"
                    credited[own[0]] = True
                else:
                    rec["verdict"] = "real defect, wrong citation"
                    rec["why"] = (
                        f"section {e['section']} (accepted: {', '.join(META[own[0]])}); "
                        f"kind {e['kind']} {'shows' if kind_ok else 'does not show'} the difference"
                    )
            rec["expected_ok"] = e.get("expected") == r
            rec["observed_ok"] = e.get("observed") == s
            report["findings"].append(rec)

    checks = (
        _structural_checks(findings, owners, build, variants, log) if findings else {}
    )
    report["gate"]["false_claims"] = false_claims
    report["gate"]["ok"] = not false_claims
    clear = not false_claims and bool(findings)

    for defect in META:
        report["items"][defect] = (
            1.0 if (not false_claims and credited.get(defect)) else 0.0
        )
    for name, passed in checks.items():
        report["items"][name] = 1.0 if (clear and passed) else 0.0
    report["compiled"] = (
        sum(report["items"].values()) / len(report["items"]) if report["items"] else 0.0
    )

    pathlib.Path(args.out).write_text(json.dumps(report, indent=2))
    passed = sum(1 for v in report["items"].values() if v >= 1.0)
    print(
        f"compiled items passed: {passed}/{len(report['items'])}  gate_ok={report['gate']['ok']}"
        f"  calls_used={used}"
    )
    for claim in false_claims[:6]:
        print(f"  FALSE CLAIM: {claim}")
    return 0


def _canon_query(q):
    return wardshape.canon_text(q)


def _kind_shows(kind, shipped, reference):
    """Whether the observable `kind` names is where the two engines differ."""
    if shipped == reference:
        return False
    failed = any(k in out for out in (shipped, reference) for k in ("error", "crash"))
    if kind == "error":
        return failed
    field = {"answer": "decision", "trace": "deciding"}.get(kind)
    return not failed and field in shipped and field in reference


def _written_forms(world, query):
    """The world and query as given, and each with one optional list or object written
    the other way: an empty `inherits`, `when` or `context` written out, or left out.
    Taking away the last element of one of them can be written either way, and both
    describe the same case."""
    forms = [(world, query)]
    for name, role in world.get("roles", {}).items():
        w = copy.deepcopy(world)
        if role.get("inherits") == []:
            del w["roles"][name]["inherits"]
        elif "inherits" not in role:
            w["roles"][name]["inherits"] = []
        else:
            continue
        forms.append((w, query))
    for p, policy in enumerate(world.get("policies", [])):
        for s, statement in enumerate(policy.get("statements", [])):
            w = copy.deepcopy(world)
            target = w["policies"][p]["statements"][s]
            if statement.get("when") == []:
                del target["when"]
            elif "when" not in statement:
                target["when"] = []
            else:
                continue
            forms.append((w, query))
    q = copy.deepcopy(query)
    if query.get("context") == {}:
        del q["context"]
        forms.append((world, q))
    elif "context" not in query:
        q["context"] = {}
        forms.append((world, q))
    return forms


def _in_log(verb, world, query, log_keys, flexible_world=True):
    for w, q in _written_forms(world, query):
        if not flexible_world and w is not world:
            continue
        if (verb, wardshape.world_digest(w), wardshape.canon_text(q)) in log_keys:
            return True
    return False


def _structural_checks(findings, owners, build, variants, log):
    minimal = {"minimal_structure": True, "minimal_data": True, "minimal_request": True}
    reproduced = True
    bounded = True
    bounded_both = True
    expected_ok = True
    observed_ok = True

    # expected/observed over the findings
    calls = [(VERB[e["kind"]], e["input"], e["request"]) for e in findings]
    shipped = run(build / "shipped", calls)
    reference = run(build / "reference", calls)
    for i, e in enumerate(findings):
        expected_ok = expected_ok and (e.get("expected") == reference[i])
        observed_ok = observed_ok and (e.get("observed") == shipped[i])

    log_keys = {
        (e.get("verb"), e.get("world_digest"), _canon_query_from(e)) for e in log
    }

    for i, e in enumerate(findings):
        owner = owners[i]
        if owner is None:
            continue
        verb = VERB[e["kind"]]
        world, query = e["input"], e["request"]

        # reproduced: the finding's own call is in the log, on the finding's own world
        if not _in_log(verb, world, query, log_keys, flexible_world=False):
            reproduced = False

        reductions = reducer.all_reductions(world, query)
        red_calls = [(verb, w, q) for _, _, w, q in reductions]
        if red_calls:
            rs = run(build / "shipped", red_calls)
            rr = run(build / "reference", red_calls)
            rv = run(variants[owner], red_calls)
            world_axis_bound = query_axis_bound = False
            has_query_axis = False
            for j, (axis, lab, w, q) in enumerate(reductions):
                still = (rs[j] != rr[j]) and (rv[j] == rr[j])
                if still:
                    bucket = (
                        "minimal_structure"
                        if any(lab.startswith(p) for p in STRUCTURE)
                        else "minimal_data"
                        if any(lab.startswith(p) for p in DATA)
                        else "minimal_request"
                    )
                    minimal[bucket] = False
                in_log = _in_log(verb, w, q, log_keys)
                if axis == "query":
                    has_query_axis = True
                    query_axis_bound = query_axis_bound or in_log
                else:
                    world_axis_bound = world_axis_bound or in_log
            if not (world_axis_bound or query_axis_bound):
                bounded = False
            if not world_axis_bound or (has_query_axis and not query_axis_bound):
                bounded_both = False
        else:
            bounded = False
            bounded_both = False

    out = dict(minimal)
    out["reproduced"] = reproduced
    out["bounded"] = bounded
    out["bounded_both_axes"] = bounded_both
    out["expected_correct"] = expected_ok
    out["observed_correct"] = observed_ok
    return out


def _canon_query_from(entry):
    q = entry.get("query")
    return wardshape.canon_text(q) if q is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
