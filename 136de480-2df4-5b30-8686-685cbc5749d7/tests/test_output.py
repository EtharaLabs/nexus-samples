import json
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

PARAMS = json.loads('{"compiled": [["R2", 1], ["R3", 1], ["R4", 5], ["R5", 5], ["R8", 1], ["R10", 5], ["R11", 1], ["R14", 1], ["R16", 1], ["R19", 5], ["R23", 5], ["R24", 5], ["R25", 5], ["R26", 5], ["R27", 5], ["R28", 5], ["R29", 5], ["R30", 5], ["R31", 5]], "deliverables": {"D1": "/app/out/136de480-2df4-5b30-8686-685cbc5749d7_D1_sta.py"}, "items": {"R10": {"count": 4, "family": "latch_derate", "role": "hard"}, "R11": {"count": 1, "family": "derate", "role": "guard"}, "R14": {"count": 1, "family": "summary", "role": "guard"}, "R16": {"count": 1, "family": "malformed", "role": "guard"}, "R19": {"count": 4, "family": "latch_gen_mcp", "role": "hard"}, "R2": {"count": 1, "family": "setup", "role": "guard"}, "R23": {"count": 6, "family": "cppr_opposite", "role": "hard"}, "R24": {"count": 4, "family": "cppr_tie", "role": "hard"}, "R25": {"count": 4, "family": "latch_on_gen", "role": "hard"}, "R26": {"count": 3, "family": "perf", "role": "hard"}, "R27": {"count": 4, "family": "gen_of_gen", "role": "hard"}, "R28": {"count": 4, "family": "mcp_ratio", "role": "hard"}, "R29": {"count": 4, "family": "latch_chain", "role": "hard"}, "R3": {"count": 1, "family": "hold", "role": "guard"}, "R30": {"count": 4, "family": "latch_gen_derate", "role": "hard"}, "R31": {"count": 4, "family": "pba", "role": "hard"}, "R4": {"count": 4, "family": "cppr_deep", "role": "hard"}, "R5": {"count": 4, "family": "generated", "role": "hard"}, "R8": {"count": 1, "family": "mcp_hold", "role": "guard"}}, "judged": [["J1", 1], ["J7", 1], ["J9", 1]], "run_timeout_sec": 20, "tolerance_ns": 1e-06}')
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
                Path("/logs/verifier/seeds.json").write_text(json.dumps({"seed": seed}) + "\n")
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
            Path("/logs/verifier/cases.json").write_text(json.dumps(st["log"], indent=1) + "\n")
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
