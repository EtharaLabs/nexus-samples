# FORGE-CANARY-BEGIN
# FORGE-CANARY-SLOT-1: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-2: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-3: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-SLOT-4: 0000000000000000000000000000000000000000000000000000000000000000
# FORGE-CANARY-END
"""Regenerate every derived byte of the bundle from solution/grounding.yaml and refuse on drift.

Run from the bundle root: python3 solution/recompute.py
"""

import hashlib
import importlib.util
import itertools
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import NoReturn

import yaml

sys.dont_write_bytecode = True
ROOT = Path.cwd()
PLACEHOLDER_BLOCK = (
    "{c} FORGE-CANARY-BEGIN\n"
    + "".join(f"{{c}} FORGE-CANARY-SLOT-{n}: {'0' * 64}\n" for n in range(1, 5))
    + "{c} FORGE-CANARY-END\n"
)
WEIGHT_SCALE = {1, 3, 5}
DIMENSIONS = ["outcome", "coverage", "constraints", "robustness", "process", "craft"]
OUTCOME_CLASSES = {"VALUE", "EFFECT", "ABSENCE", "INVARIANT", "ORDERING", "DIVERGENCE"}
TARGETS = {
    "deliverable_file",
    "database_state",
    "process_state",
    "filesystem_state",
    "verifier_log",
}
ITEM_KEYS = {
    "id",
    "obligation",
    "dimension",
    "weight",
    "negate",
    "type",
    "evaluation_target",
    "criterion",
    "judgment",
    "evidence",
    "mode",
    "drafting",
}
JUDGE_FIXED = {
    "backend": "codex",
    "model": "openai/gpt-5.6-sol",
    "auth": "chatgpt-subscription",
    "force_subscription": True,
    "codex_cli_version": "0.164.0",
    "mode": "batched",
    "isolated": False,
    "cwd": "/app",
    "reasoning_effort": "high",
    "timeout_sec": 600,
    "guard": "penalize",
}
JUDGE_KEYS = set(JUDGE_FIXED) | {"files"}
REWARDKIT_ROUNDING = 4
ROUNDING_TOLERANCE = 1e-4
GENERATORS = {"gen_design.py", "sta_ref.py"}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"recompute: {message}")


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        fail(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canary(marker: str) -> str:
    return PLACEHOLDER_BLOCK.replace("{c}", marker)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def drafting_digests(item: dict) -> dict:
    prompt = {k: v for k, v in item.items() if k not in {"criterion", "drafting"}}
    return {
        "prompt_sha256": sha256(
            json.dumps(prompt, sort_keys=True, separators=(",", ":"))
        ),
        "output_sha256": sha256(item["criterion"]),
    }


def check_prose(item: dict) -> None:
    text = item["criterion"]
    bare = re.sub(r"`[^`]*`", "", text)
    if "\u2014" in text or "--" in bare:
        fail(f"{item['id']}: criterion carries an em-dash")
    if not bare.isascii():
        fail(f"{item['id']}: criterion is not plain ASCII outside code spans")
    if not text.endswith(".") or re.search(r"\.\s+[A-Z]", bare[:-1]):
        fail(f"{item['id']}: criterion is not one declarative sentence")
    if re.search(
        r"\b(may|might|should|could|perhaps|possibly|probably|ideally)\b", bare, re.I
    ):
        fail(f"{item['id']}: criterion hedges")
    if not text.startswith(item["obligation"] + " "):
        fail(
            f"{item['id']}: criterion does not open with its obligation {item['obligation']}"
        )


def check_rubric(g: dict) -> None:
    obligations, items = g["obligations"], g["rubric"]
    if g["dimensions"] != DIMENSIONS:
        fail("dimension vocabulary differs from the contract's 9g default")
    if set(obligations) != set(g["deliverables"]):
        fail("obligations differ from the deliverable manifest ids")
    seen: set[str] = set()
    for item in items:
        if set(item) - {"residue"} != ITEM_KEYS:
            fail(
                f"{item.get('id')}: keys {sorted(set(item) ^ ITEM_KEYS)} break the closed item schema"
            )
        if item["id"] in seen:
            fail(f"duplicate rubric id {item['id']}")
        seen.add(item["id"])
        weight = item["weight"]
        if (
            isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight not in WEIGHT_SCALE
        ):
            fail(f"{item['id']}: weight {weight!r} is off the 1/3/5 scale")
        if not isinstance(item["negate"], bool):
            fail(f"{item['id']}: negate is not a boolean")
        if item["obligation"] not in obligations or item["dimension"] not in DIMENSIONS:
            fail(
                f"{item['id']}: cell {item['obligation']}/{item['dimension']} is outside the grid"
            )
        if item["type"] not in OUTCOME_CLASSES:
            fail(f"{item['id']}: outcome class {item['type']} is unknown")
        if item["mode"] not in {"compiled", "judged"} or item["judgment"] != "binary":
            fail(f"{item['id']}: mode or judgment is unknown")
        if (
            item["evaluation_target"] not in TARGETS
            or not set(item["evidence"]) <= TARGETS
        ):
            fail(f"{item['id']}: evidence is outside the target vocabulary")
        if (item["mode"] == "judged") != bool(item.get("residue")):
            fail(
                f"{item['id']}: a judged item names its residue and a compiled item names none"
            )
        if (item["type"] == "ABSENCE") != item["negate"]:
            fail(
                f"{item['id']}: a prohibition carries negate true and every other item negate false"
            )
        check_prose(item)
    not_applicable = g.get("grid_not_applicable") or {}
    for obligation, dimension in itertools.product(obligations, DIMENSIONS):
        held = any(
            i["obligation"] == obligation and i["dimension"] == dimension for i in items
        )
        reason = not_applicable.get(obligation, {}).get(dimension)
        if held == bool(reason):
            fail(
                f"grid cell {obligation}/{dimension} needs exactly one of an item or a not_applicable reason"
            )
    for dimension in DIMENSIONS:
        if not any(i["dimension"] == dimension for i in items) and not all(
            not_applicable.get(o, {}).get(dimension) for o in obligations
        ):
            fail(f"dimension {dimension} holds no item")
    descriptions = [" ".join(i["criterion"].lower().split()) for i in items]
    if len(set(descriptions)) != len(descriptions):
        fail("two rubric items state the same check")
    judged_evidence = {e for i in items if i["mode"] == "judged" for e in i["evidence"]}
    compiled_d1 = {
        e
        for i in items
        if i["mode"] == "compiled" and i["obligation"] == "D1"
        for e in i["evidence"]
    }
    if judged_evidence & compiled_d1:
        fail("a judged item grades the same D1 evidence as a compiled item")
    for item in items:
        if item["drafting"] != drafting_digests(item):
            fail(f"{item['id']}: drafting digests do not match the frozen item")
    compiled = {i["id"] for i in items if i["mode"] == "compiled"}
    if "core" in g:
        fail("the single-stage reward has no core list")
    if set(g["hidden_cases"]["items"]) != compiled:
        fail("hidden case plan does not cover exactly the D1 compiled items")
    if (
        sum(v["count"] for v in g["hidden_cases"]["items"].values())
        != g["hidden_cases"]["total"]
        or g["hidden_cases"]["total"] < 30
    ):
        fail("hidden case count differs from its declared total or is below 30")


def item_weights(g: dict) -> dict[str, int]:
    weights = {"test_output": 0, "judge": 0}
    for item in g["rubric"]:
        weights["test_output" if item["mode"] == "compiled" else "judge"] += item[
            "weight"
        ]
    return weights


def carrier_weights(g: dict) -> dict[str, int]:
    """Slot 7 carries fixed carrier weights (fairness_scale_rework.reward), not item-weight sums."""
    fixed = g["reward_ladder"]["carrier_weights"]
    if fixed != {"test_output": 9, "judge": 1}:
        fail(f"carrier weights {fixed} differ from the approved fixed 9:1")
    return dict(fixed)


def subset_sums(weights: list[int]) -> set[int]:
    sums = {0}
    for weight in weights:
        sums |= {s + weight for s in sums}
    return sums


def check_weights(g: dict) -> None:
    carriers = carrier_weights(g)
    share = carriers["judge"] / sum(carriers.values())
    if share * 3 > 1:
        fail(f"judged share {share} exceeds one third")
    items = item_weights(g)
    if items != g["reward_ladder"]["item_weight_totals"]:
        fail(f"item weight totals {items} differ from {g['reward_ladder']['item_weight_totals']}")


def expected_reward(g: dict, failed: set[str], judge_score: float) -> float:
    """The Reward Kit reward of a run that fails exactly the compiled items `failed`."""
    carriers = carrier_weights(g)
    compiled = [i for i in g["rubric"] if i["mode"] == "compiled"]
    total = sum(i["weight"] for i in compiled)
    t = round(
        sum(i["weight"] for i in compiled if i["id"] not in failed) / total,
        REWARDKIT_ROUNDING,
    )
    return round(
        (carriers["test_output"] * t + carriers["judge"] * judge_score)
        / sum(carriers.values()),
        REWARDKIT_ROUNDING,
    )


def check_statement(g: dict) -> None:
    digest = hashlib.sha256((ROOT / "instruction.md").read_bytes()).hexdigest()
    if g["statement"]["sha256"] != digest:
        fail(f"instruction.md digest {digest} differs from solution/grounding.yaml")


def check_derivation(g: dict) -> None:
    """Every rule the reference applies is stated in instruction.md or cited from a public standard."""
    rows = g.get("derivation_table") or []
    if not rows:
        fail("the derivation table is empty")
    points = set(g["statement"]["open_points"])
    for row in rows:
        source = row.get("source") or ""
        if not row.get("rule") or not source.startswith(("stated: ", "cited: ")):
            fail(f"derivation row is neither stated nor cited: {row}")
        if set(row) - {"rule", "source"}:
            fail(f"derivation row carries keys beyond rule and source: {row['rule']}")
        for label in re.findall(r"\bS\d+\b", source):
            if label not in points:
                fail(f"derivation row cites {label}, which is not a statement point")


def check_known_wrong(g: dict) -> None:
    rejected = {c for k in g["known_wrong"] for c in k["rejected_by"]}
    ids = {i["id"] for i in g["rubric"]}
    if rejected != ids:
        fail(
            f"known-wrong routes do not close over the rubric: {sorted(ids ^ rejected)}"
        )


def check_judge(g: dict) -> dict:
    judge = g.get("judge")
    if not isinstance(judge, dict) or set(judge) != JUDGE_KEYS:
        fail(f"grounding judge block must carry exactly {sorted(JUDGE_KEYS)}")
    drift = {k: judge[k] for k, v in JUDGE_FIXED.items() if judge[k] != v}
    if drift:
        fail(f"grounding judge block differs from the bound judge: {drift}")
    if not judge["files"] or not set(judge["files"]) <= set(g["deliverables"].values()):
        fail("judge files must be a non-empty subset of the deliverables")
    return judge


def check_reward_ladder(g: dict) -> None:
    ladder = g["reward_ladder"]
    meta = tomllib.loads((ROOT / "task.toml").read_text())["metadata"]
    if ladder["aggregation"] != "weighted-mean":
        fail("the reward ladder must be the single weighted mean")
    if float(meta["discrimination_weight"]) != float(ladder["discrimination_weight"]):
        fail(
            f"task.toml discrimination_weight {meta['discrimination_weight']} differs from the declared {ladder['discrimination_weight']}"
        )


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    fail(f"no TOML rendering for {value!r}")


def render_judge(g: dict, judge: dict) -> str:
    lines = [
        "[judge]",
        f"judge = {toml_value(judge['backend'])}",
        f"model = {toml_value(judge['model'])}",
        f"version = {toml_value(judge['codex_cli_version'])}",
        f"files = {toml_value(judge['files'])}",
        f"mode = {toml_value(judge['mode'])}",
        f"isolated = {toml_value(judge['isolated'])}",
        f"cwd = {toml_value(judge['cwd'])}",
        f"reasoning_effort = {toml_value(judge['reasoning_effort'])}",
        f"timeout = {toml_value(judge['timeout_sec'])}",
        f"guard = {toml_value(judge['guard'])}",
        "",
        "[scoring]",
        'aggregation = "weighted-mean"',
    ]
    for item in g["rubric"]:
        if item["mode"] != "judged":
            continue
        lines += [
            "",
            "[[criterion]]",
            f"id = {toml_value(item['id'])}",
            f"name = {toml_value(item['id'])}",
            f"description = {toml_value(item['criterion'])}",
            'type = "binary"',
            f"weight = {toml_value(item['weight'])}",
            f"negate = {toml_value(item['negate'])}",
            "",
            "[criterion.annotations]",
            'mode = "judged"',
            f"type = {toml_value(item['type'])}",
            f"obligation = {toml_value(item['obligation'])}",
            f"dimension = {toml_value(item['dimension'])}",
            f"evidence = {toml_value(item['evidence'])}",
            f"residue = {toml_value(item['residue'])}",
        ]
    return "\n".join(lines) + "\n"


def render_tables(g: dict) -> dict[str, str]:
    w = carrier_weights(g)
    reward = (
        "[[reward]]\n"
        'name = "reward"\n'
        'aggregation = "weighted-mean"\n'
        f"weights = {{ test_output = {w['test_output']}, judge = {w['judge']} }}\n"
        "\n"
        "[[reward]]\n"
        'name = "test_output"\n'
        'aggregation = "weighted-mean"\n'
        "weights = { test_output = 1, judge = 0 }\n"
        "\n"
        "[[reward]]\n"
        'name = "judge"\n'
        'aggregation = "weighted-mean"\n'
        "weights = { test_output = 0, judge = 1 }\n"
        "\n"
        "[scoring.test_output]\n"
        'aggregation = "weighted-mean"\n'
    )
    return {"tests/reward.toml": reward}


TEST_TEMPLATE = """import json
import os
import random
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import rewardkit
from rewardkit import criterion

import gen_design

PARAMS = json.loads(__PARAMS__)
TOL = PARAMS["tolerance_ns"]
D1 = PARAMS["deliverables"]["D1"]
UNPRIVILEGED = 1000
REPORT_KEYS = {"wns_setup", "tns_setup", "wns_hold", "tns_hold", "endpoints", "arrivals", "borrow", "pba_setup"}
ARRIVAL_KEYS = {"late_rise", "late_fall", "early_rise", "early_fall"}
PBA_COUNT = 5
SUMMARY_KEYS = ("wns_setup", "tns_setup", "wns_hold", "tns_hold")
_LOCK = threading.Lock()
_STATE = {}


def _state():
    with _LOCK:
        if not _STATE:
            raw = os.environ.get("REWARD_SEED", "")
            seed = int(raw) if raw.isdigit() else secrets.randbits(48)
            work = Path(tempfile.mkdtemp(prefix="sta-verify-"))
            os.chmod(work, 0o755)
            _STATE.update(seed=seed, work=work, items={}, n=0, log=[])
            try:
                Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
                Path("/logs/verifier/seeds.json").write_text(json.dumps({"seed": seed}) + "\\n")
            except OSError:
                _STATE["seed_log"] = "unwritable"
        return _STATE


def _run(texts):
    st = _state()
    with _LOCK:
        st["n"] += 1
        tag = f"case{st['n']}"
    root = st["work"] / tag
    root.mkdir()
    for name, text in texts.items():
        (root / name).write_text(text)
        os.chmod(root / name, 0o444)
    out = st["work"] / f"{tag}-out"
    out.mkdir()
    extra = {}
    if os.geteuid() == 0:
        os.chown(out, UNPRIVILEGED, UNPRIVILEGED)
        extra = {"user": UNPRIVILEGED, "group": UNPRIVILEGED}
    target = out / "report.json"
    argv = ["python3", D1, "--lib", str(root / "cells.nldm"), "--netlist", str(root / "top.v"), "--sdc", str(root / "top.sdc"), "--out", str(target)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=PARAMS["run_timeout_sec"], cwd=str(out),
                              env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}, **extra)
    except (OSError, subprocess.TimeoutExpired):
        return None, None, target.exists()
    report = None
    if done.returncode == 0:
        try:
            report = json.loads(target.read_text())
        except (OSError, ValueError):
            report = None
    return done.returncode, report, target.exists()


def _note(entry):
    st = _state()
    with _LOCK:
        st["log"].append(entry)
        try:
            Path("/logs/verifier/cases.json").write_text(json.dumps(st["log"], indent=1) + "\\n")
        except OSError:
            pass


def _cases(item):
    st = _state()
    with _LOCK:
        cached = st["items"].get(item)
    if cached is not None:
        return cached
    spec = PARAMS["items"][item]
    rows = []
    for k in range(spec["count"]):
        started = time.monotonic()
        case, want = gen_design.pick_case(spec["family"], f"{st['seed']}:{item}:{k}")
        ran = time.monotonic()
        code, got, _written = _run(gen_design.texts(case))
        _note({"item": item, "case": k, "family": spec["family"], "reference_sec": round(ran - started, 3),
               "d1_sec": round(time.monotonic() - ran, 3), "exit": code})
        rows.append((case, want, got))
    with _LOCK:
        st["items"][item] = rows
    return rows


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(a, b):
    if a is None or b is None:
        return a is None and b is None
    return _is_num(a) and _is_num(b) and abs(a - b) <= TOL


def _same(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if a is None or _is_num(a):
        return _num(a, b)
    return a == b


def _optional_num(v):
    return v is None or _is_num(v)


def _schema(r):
    if not isinstance(r, dict) or set(r) != REPORT_KEYS:
        return False
    if not all(_optional_num(r[k]) for k in SUMMARY_KEYS):
        return False
    ep, ar, bo, pba = r["endpoints"], r["arrivals"], r["borrow"], r["pba_setup"]
    if not isinstance(ep, dict) or not all(isinstance(v, dict) and set(v) == {"setup", "hold"} and all(_optional_num(x) for x in v.values()) for v in ep.values()):
        return False
    if not isinstance(ar, dict) or not all(isinstance(v, dict) and set(v) == ARRIVAL_KEYS and all(_optional_num(x) for x in v.values()) for v in ar.values()):
        return False
    if not isinstance(bo, dict) or not all(_optional_num(v) for v in bo.values()):
        return False
    return isinstance(pba, dict) and len(pba) <= PBA_COUNT and set(pba) <= set(ep) and all(_is_num(v) for v in pba.values())


def _rows(item):
    rows = _cases(item)
    return rows if rows and all(_schema(got) for _case, _want, got in rows) else []


def _slacks(want, got, names, fields):
    try:
        return all(_num(want["endpoints"][e][f], got["endpoints"][e][f]) for e in names for f in fields)
    except (TypeError, KeyError):
        return False


def _endpoints_match(want, got, fields):
    if not isinstance(got, dict) or not isinstance(got.get("endpoints"), dict) or set(got["endpoints"]) != set(want["endpoints"]):
        return False
    return _slacks(want, got, list(want["endpoints"]), fields)


def _all_endpoints(item, fields):
    rows = _rows(item)
    return bool(rows) and all(_endpoints_match(want, got, fields) for _case, want, got in rows)


def _focused(item, fields):
    rows = _rows(item)
    family = PARAMS["items"][item]["family"]
    for case, want, got in rows:
        names = gen_design.focus(family, case, want)
        if not names or not _slacks(want, got, names, fields):
            return False
    return bool(rows)


def _part(want, got, key):
    return isinstance(got, dict) and key in got and _same(want[key], got[key])


def _latch_q(want, got):
    names = [p for p in want["arrivals"] if p.split("/")[0] in {e.split("/")[0] for e in want["borrow"]} and p.endswith("/Q")]
    return all(p in got["arrivals"] and _same(want["arrivals"][p], got["arrivals"][p]) for p in names)


def _latch_report(item):
    rows = _rows(item)
    return bool(rows) and all(
        _endpoints_match(want, got, ("setup", "hold")) and _part(want, got, "borrow") and _part(want, got, "arrivals")
        for _case, want, got in rows
    )


@criterion(shared=True)
def R2(workspace: Path) -> bool:
    return _all_endpoints("R2", ("setup",))


@criterion(shared=True)
def R3(workspace: Path) -> bool:
    return _all_endpoints("R3", ("hold",))


@criterion(shared=True)
def R4(workspace: Path) -> bool:
    return _all_endpoints("R4", ("setup", "hold"))


@criterion(shared=True)
def R5(workspace: Path) -> bool:
    return _focused("R5", ("setup", "hold"))


@criterion(shared=True)
def R8(workspace: Path) -> bool:
    return _focused("R8", ("hold",))


@criterion(shared=True)
def R10(workspace: Path) -> bool:
    rows = _rows("R10")
    return bool(rows) and all(_part(want, got, "borrow") and _endpoints_match(want, got, ("setup",)) for _case, want, got in rows)


@criterion(shared=True)
def R11(workspace: Path) -> bool:
    return _all_endpoints("R11", ("setup", "hold"))


@criterion(shared=True)
def R14(workspace: Path) -> bool:
    rows = _rows("R14")
    return bool(rows) and all(all(_num(want[k], got[k]) for k in SUMMARY_KEYS) for _case, want, got in rows)


@criterion(shared=True)
def R16(workspace: Path) -> bool:
    st = _state()
    if not Path(D1).is_file():
        return False
    for k in range(PARAMS["items"]["R16"]["count"]):
        seed = f"{st['seed']}:R16:{k}"
        kind = random.Random(seed).choice(gen_design.MALFORMED)
        valid_code, _report, valid_written = _run(gen_design.texts(gen_design.make_case("smoke", seed)))
        if valid_code != 0 or not valid_written:
            return False
        code, _report, written = _run(gen_design.malformed_case(kind, seed))
        if code != 2 or written:
            return False
    return PARAMS["items"]["R16"]["count"] > 0


@criterion(shared=True)
def R19(workspace: Path) -> bool:
    return _latch_report("R19")


@criterion(shared=True)
def R23(workspace: Path) -> bool:
    return _all_endpoints("R23", ("setup", "hold"))


@criterion(shared=True)
def R24(workspace: Path) -> bool:
    return _all_endpoints("R24", ("setup", "hold"))


@criterion(shared=True)
def R25(workspace: Path) -> bool:
    return _latch_report("R25")


@criterion(shared=True)
def R26(workspace: Path) -> bool:
    rows = _rows("R26")
    return bool(rows) and all(
        _endpoints_match(want, got, ("setup", "hold"))
        and all(_part(want, got, k) for k in ("arrivals", "borrow", "pba_setup"))
        and _num(want["wns_setup"], got["wns_setup"])
        and _num(want["wns_hold"], got["wns_hold"])
        for _case, want, got in rows
    )


@criterion(shared=True)
def R27(workspace: Path) -> bool:
    return _all_endpoints("R27", ("setup", "hold"))


@criterion(shared=True)
def R28(workspace: Path) -> bool:
    return _all_endpoints("R28", ("setup", "hold"))


@criterion(shared=True)
def R29(workspace: Path) -> bool:
    rows = _rows("R29")
    return bool(rows) and all(
        _part(want, got, "borrow") and _latch_q(want, got) and _endpoints_match(want, got, ("setup",))
        for _case, want, got in rows
    )


@criterion(shared=True)
def R30(workspace: Path) -> bool:
    rows = _rows("R30")
    return bool(rows) and all(
        _part(want, got, "borrow") and _endpoints_match(want, got, ("setup", "hold")) for _case, want, got in rows
    )


@criterion(shared=True)
def R31(workspace: Path) -> bool:
    rows = _rows("R31")
    return bool(rows) and all(
        _part(want, got, "pba_setup") and _endpoints_match(want, got, ("setup",)) for _case, want, got in rows
    )


for _id, _weight in PARAMS["compiled"]:
    getattr(rewardkit, _id)(weight=_weight, name=_id)
"""


def render_tests(g: dict) -> str:
    params = {
        "deliverables": g["deliverables"],
        "items": g["hidden_cases"]["items"],
        "tolerance_ns": g["tolerance_ns"],
        "run_timeout_sec": g["run_timeout_sec"],
        "compiled": [
            [i["id"], i["weight"]] for i in g["rubric"] if i["mode"] == "compiled"
        ],
        "judged": [
            [i["id"], i["weight"]] for i in g["rubric"] if i["mode"] == "judged"
        ],
    }
    return TEST_TEMPLATE.replace("__PARAMS__", repr(json.dumps(params, sort_keys=True)))


def render_solve(g: dict) -> str:
    return (
        "#!/bin/bash\n"
        + canary("#")
        + "set -euo pipefail\n"
        + f"install -m 0644 /solution/sta.py {g['deliverables']['D1']}\n"
    )


STEPS = [
    (
        "Parse the Liberty subset (units, `lu_table_template` variable orders and breakpoints, `wire_load`, pins, `ff` and `latch` groups, timing arcs and constraint tables), the structural Verilog, and the SDC subset; exit 2 on any malformed or undefined input.",
        ["R16"],
    ),
    (
        "Evaluate every NLDM table in its template's variable order with linear interpolation and linear extrapolation, and build net loads from pin capacitance, `set_load`, and the default wire load.",
        ["R2", "R3", "J1"],
    ),
    (
        "Mark the clock network from each clock source and generated-clock pin, recursively for a generated clock whose source register runs on another generated clock; derive each generated waveform from its master through `-divide_by`, `-multiply_by`, or `-edges`; propagate late and early clock arrivals with clock derates, recording the arc input that set each arrival with the stated tie rule, or use ideal zero latency and `set_clock_transition`.",
        ["R5", "R27"],
    ),
    (
        "Propagate late and early arrivals and slews per pin, transition, and launch group (launching clock, edge, and exception state) in one topological pass through the unateness of every arc, with data derates, so the cost grows with the arrivals kept rather than with the number of launch groups times the graph.",
        ["R11", "R26", "J7"],
    ),
    (
        "Pair launch and capture edges over the common period of the two periods taken as exact rationals, shift setup by multicycle setup at the capture period, and take the hold relationship as the setup relationship minus the smaller of the two periods minus the multicycle hold multiplier times the launch period.",
        ["R8", "R28"],
    ),
    (
        "Time setup with late data and the early capture clock and hold with early data and the late capture clock; trace the launch and capture clock paths through every generated-clock source register, credit CPPR at their last common pin as its late minus early arrival, and credit nothing where the two paths cross that pin with opposite transitions.",
        ["R4", "R24", "R23"],
    ),
    (
        "Time latches at the opening edge with borrowing bounded by the open window less the setup constraint and never below 0, launch Q at the latch's own opening edge from the enable and from every borrowing D arrival, so a chain of borrowing latches passes time from latch to latch; latches on a generated clock use its own edges, derates, and CPPR.",
        ["R10", "R19", "R25", "R29", "R30"],
    ),
    (
        "Re-time the worst five register and port setup endpoints along the path that set each one's graph slack, with the slew propagated along that path and the late data derate, and report `pba_setup`.",
        ["R31"],
    ),
    (
        "Report endpoints, WNS and TNS, arrivals, borrow, and `pba_setup` in the stated schema, computing everything from the given files.",
        ["R14", "J9"],
    ),
]


def render_truth(g: dict) -> str:
    weights = carrier_weights(g)
    covered = {c for _, checks in STEPS for c in checks}
    ids = {i["id"] for i in g["rubric"]}
    if covered != ids:
        fail(
            f"the golden trajectory does not cover every rubric item: {sorted(covered ^ ids)}"
        )
    hard = [k for k, v in g["hidden_cases"]["items"].items() if v["role"] == "hard"]
    guard = [k for k, v in g["hidden_cases"]["items"].items() if v["role"] == "guard"]
    lines = [
        canary("<!--").replace("\n", " -->\n"),
        "# Ground truth",
        "",
        "GENERATED SECTION. DO NOT HAND-EDIT.",
        "",
        f"Design id `{g['design_id']}`, slot {g['slot']}, archetype `{g['archetype']}`, category `{g['category']}`.",
        "",
        "Expected reports come from `tests/sta_ref.py` over the generator's structured model; the oracle `solution/sta.py` is a separately written text parser and analyser whose reports agree with the reference within 1e-6 ns on every hidden family (recorded in the run's feasibility evidence). Every rule the reference applies is stated in `instruction.md` or cited from Liberty NLDM and SDC 2.1 (`derivation_table` in `solution/grounding.yaml`). The two designs under `/app/design/` and `/app/design/example/` are parsing samples only: no report, slack, or other reference number for them ships anywhere in the environment, and neither is graded.",
        "",
        "## Deliverables",
        "",
        *[f"- `{k}`: `{v}`" for k, v in g["deliverables"].items()],
        "",
        "## Golden trajectory",
        "",
    ]
    for number, (action, checks) in enumerate(STEPS, 1):
        lines.append(
            f"{number}. {action} Deliverable `D1`; satisfies {', '.join(f'`{c}`' for c in checks)}."
        )
    lines += [
        "",
        "## Rubric",
        "",
        "| Item | Obligation | Dimension | Weight | Negate | Class | Mode | Criterion |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i in g["rubric"]:
        lines.append(
            f"| `{i['id']}` | {i['obligation']} | {i['dimension']} | {i['weight']} | {str(i['negate']).lower()} | {i['type']} | {i['mode']} | {i['criterion']} |"
        )
    lines += ["", "## Grid cells without an item", ""]
    cells = [
        f"- {obligation} / {dimension}: {reason}"
        for obligation, rows in (g.get("grid_not_applicable") or {}).items()
        for dimension, reason in rows.items()
    ]
    lines += cells or ["- none: every obligation and dimension cell holds an item"]
    lines += [
        "",
        "## Hidden cases",
        "",
        f"{g['hidden_cases']['rule']}. {g['hidden_cases']['total']} graded D1 cases: hard families {', '.join(f'`{k}`' for k in hard)} at weight 5 and one-case guards {', '.join(f'`{k}`' for k in guard)} at weight 1.",
        "",
    ]
    lines += [
        f"- `{k}` ({v['role']}): {v['count']} x `{v['family']}`"
        for k, v in g["hidden_cases"]["items"].items()
    ]
    lines += [
        "",
        "## Reward",
        "",
        "`tests/test.sh` scores one stage. When D1 is absent, empty, or does not byte-compile it writes reward 0.0 for `reward`, `test_output`, and `judge` inline and runs neither Reward Kit nor the judge, so the negated judged items never pay on an absent D1. Otherwise it runs Reward Kit once over `tests/test_output.py`, `tests/reward.toml`, and `tests/judge.toml`; a Reward Kit failure leaves no reward file and is a verifier error, never a pass.",
        "",
        f"`tests/reward.toml` fixes the carrier weights at test_output {weights['test_output']} and judge {weights['judge']}: the reward is 0.9 times the weighted mean of the compiled items in `tests/test_output.py` (item weights summing to {item_weights(g)['test_output']}) plus 0.1 times the weighted mean of the judged items in `tests/judge.toml` (item weights summing to {item_weights(g)['judge']}) under the `{g['judge']['backend']}` agent judge, model `{g['judge']['model']}`, guard `{g['judge']['guard']}`. Reward Kit rounds each mean and the reward to four decimals. A run that fails only the guard `R16`, with the judge at 1.0, scores {expected_reward(g, {'R16'}, 1.0)}; a run that fails only the hard item `R26` scores {expected_reward(g, {'R26'}, 1.0)}. A trial passes only when its reward is exactly 1.0; the mean reward is reported beside the pass rate.",
        "",
        f"`discrimination_weight = {g['reward_ladder']['discrimination_weight']}`: {g['reward_ladder']['reason']}.",
        "",
        "## Rejected routes",
        "",
    ]
    lines += [
        f"- `{k['id']}` {k['route']}: rejected by {', '.join(f'`{c}`' for c in k['rejected_by'])}"
        for k in g["known_wrong"]
    ]
    return "\n".join(lines) + "\n"


def write_data(files: dict[str, bytes]) -> None:
    stale = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "environment/design").rglob("*")
        if p.is_file() and p.relative_to(ROOT / "environment").as_posix() not in files
    ]
    if stale:
        fail(f"environment carries files the generator does not write: {stale}")
    sums = []
    for rel, data in sorted(files.items()):
        path = ROOT / "environment" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    (ROOT / "environment/SHA256SUMS").write_text("\n".join(sums) + "\n")


def assert_clean_environment() -> None:
    found = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "environment").rglob("*")
        if p.name in GENERATORS
        or p.suffix in {".py", ".pyc", ".json"}
        or p.name == "__pycache__"
    ]
    if found:
        fail(
            f"generator, tool, or result material is on the agent-visible surface: {found}"
        )


def check_roles(g: dict) -> None:
    """Hard families carry weight 5; guards carry weight 1 with one case each."""
    weight = {i["id"]: i["weight"] for i in g["rubric"]}
    for item, spec in g["hidden_cases"]["items"].items():
        role = spec.get("role")
        if role == "hard" and weight[item] != 5:
            fail(f"{item}: a hard family carries weight 5")
        if role == "guard" and (weight[item] != 1 or spec["count"] != 1):
            fail(f"{item}: a guard carries weight 1 and exactly one case")
        if role not in {"hard", "guard"}:
            fail(f"{item}: role {role!r} is neither hard nor guard")


def main() -> None:
    g = yaml.safe_load((ROOT / "solution/grounding.yaml").read_text())
    check_rubric(g)
    check_roles(g)
    judge = check_judge(g)
    check_known_wrong(g)
    check_weights(g)
    check_reward_ladder(g)
    check_statement(g)
    check_derivation(g)
    tests = render_tests(g)
    compiled = {i["id"] for i in g["rubric"] if i["mode"] == "compiled"}
    if compiled != set(re.findall(r"^def (R\d+)\(workspace", tests, re.M)):
        fail("compiled rubric ids differ from the test_output criteria")
    assert_clean_environment()
    sys.path.insert(0, str(ROOT / "tests"))
    gen = load("gen_design", "tests/gen_design.py")
    load("sta_ref", "tests/sta_ref.py")
    env = g["environment_sample"]
    case = gen.make_case(env["family"], env["seed"])
    example = gen.example_case()
    files = {f"design/{name}": text.encode() for name, text in gen.texts(case).items()}
    files.update({f"design/example/{name}": text.encode() for name, text in gen.texts(example).items()})
    if files["design/example/top.v"] == files["design/top.v"] or files["design/example/cells.nldm"] == files["design/cells.nldm"]:
        fail("the two parsing samples share a netlist or library")
    write_data(files)
    (ROOT / "tests/judge.toml").write_text(render_judge(g, judge))
    for rel, text in render_tables(g).items():
        (ROOT / rel).write_text(text)
    (ROOT / "tests/test_output.py").write_text(tests)
    solve = ROOT / "solution/solve.sh"
    solve.write_text(render_solve(g))
    solve.chmod(0o755)
    (ROOT / "solution/TRUTH.md").write_text(render_truth(g))


if __name__ == "__main__":
    main()
