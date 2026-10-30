#!/usr/bin/env python3
"""Derive the oracle fix, golden truth, and graded criteria from the SSOT.

Single source of truth: solution/grounding.yaml plus solution/reference.py (the
correct engine). Running this regenerates solution/solve.sh, solution/TRUTH.md,
tests/test_output.py, and tests/judge.toml byte for byte. test_output.py embeds
solution/reference.py verbatim so the verifier's reference is identical to the
oracle. `--check` fails on any drift.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.dirname(HERE)
GEN = "GENERATED SECTION. DO NOT HAND-EDIT."


def _grounding():
    import yaml
    with open(os.path.join(HERE, "grounding.yaml"), "rb") as fh:
        return yaml.safe_load(fh)


def _reference_src():
    with open(os.path.join(HERE, "reference.py")) as fh:
        return fh.read()


_CNAMES = {
    "C1": "c1_clean_bytes", "C2": "c2_crash_bytes", "C3": "c3_dropped_count",
    "C4": "c4_atomic_no_tmp", "C5": "c5_clean_config2", "C6": "c6_retract_records",
    "C7": "c7_final_records", "C8": "c8_double_crash", "C9": "c9_session_boundaries",
    "C10": "c10_crash_config2", "C11": "c11_json_sorted", "C12": "c12_emit_contiguous",
    "C13": "c13_determinism", "C14": "c14_crash_before_ckpt", "C15": "c15_single_eof",
}


def _solve_sh():
    return (
        "#!/bin/bash\n"
        "# " + GEN + "\n"
        "set -euo pipefail\n"
        "# Oracle: install the reference engine as /app/stream.\n"
        "install -D -m 0755 /solution/reference.py /app/stream\n"
        'sed -i "1s|.*|#!/usr/bin/env python3|" /app/stream\n'
    )


def _truth_md(g):
    out = ["# " + GEN, "", "# Golden trajectory: " + g["task"], "",
           "The shipped /app/stream only ACKs events and writes an EOF record. The fix",
           "implements per-key gap session windows, watermark finalization, late-event",
           "retraction and re-finalization, the dropped-late count, atomic checkpointing,",
           "and exactly-once resume across chunked process restarts (suffix-only resume;",
           "state restored from the checkpoint). The verifier compares the agent's output against",
           "the embedded reference, clean and across crash/resume, over seeded traces and",
           "two field configs.", "",
           "## Compiled criteria", ""]
    for it in g["compiled_rubric"]:
        out.append("- {i} ({d}, w{w}): {c}".format(i=it["id"], d=it["dimension"], w=it["weight"], c=it["criterion"]))
    out += ["", "## Judged criteria", ""]
    for it in g["judged_rubric"]:
        out.append("- {i} ({d}, w{w}): {c}".format(i=it["id"], d=it["dimension"], w=it["weight"], c=it["criterion"]))
    out += ["", "Reward-gating: {a} and {b} (byte-exact clean and crash/resume output) fail any "
            "miscorrecting or non-exactly-once engine.".format(a=g["reward_gating_items"][0], b=g["reward_gating_items"][1]), ""]
    return "\n".join(out)


_GEN_SRC = '''
def _gen(seed, n_events=120):
    import random
    rng = random.Random(seed)
    keys = ["a", "b", "c"]
    lines = []
    seq = 0
    wm = 0
    cur = 0
    for _ in range(n_events):
        cur += rng.randrange(0, 25)
        if rng.random() < 0.45:
            wm = max(wm, cur - rng.randrange(0, 40))
            lines.append({"type": "watermark", "ts": wm})
        k = rng.choice(keys)
        if rng.random() < 0.30:
            ts = max(0, wm - rng.randrange(0, 90))
        else:
            ts = cur
        lines.append({"type": "event", "key": k, "ts": ts, "val": rng.randrange(-20, 50), "seq": seq})
        seq += 1
    for _ in range(4):
        wm += rng.randrange(20, 80)
        lines.append({"type": "watermark", "ts": wm})
    return lines
'''


def _test_output_py(g):
    c1 = g["config_1"]
    c2 = g["config_2"]
    header = '# ' + GEN + '\n"""Compiled Reward Kit criteria for the exactly-once session-window task.\n\n' \
        'The reference engine is embedded verbatim from solution/reference.py and run\n' \
        'in-process to produce the expected output; the agent\'s /app/stream is run as a\n' \
        'subprocess and compared byte for byte, clean and across a deterministic\n' \
        'chunked restarts (--resume/--final), over seeded traces and two field configs.\n"""\n'
    body = '''import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from rewardkit import criterion

STREAM = "/app/stream"
PRIMARY = 0
RETRACT_SEED = 3
BRIDGE_SEED = 5
CRASH2 = 101
CRASH4 = 102
CRASH8 = 103
CRASH10 = 104
CRASH14 = 105
CFG1 = %(c1)r
CFG2 = %(c2)r

_REF_SRC = %(ref)r
_REFNS = {}
exec(compile(_REF_SRC, "reference_embedded", "exec"), _REFNS)

%(gen)s

def _write_trace(seed):
    d = tempfile.mkdtemp(prefix="trace-", dir="/tmp")
    p = os.path.join(d, "trace.jsonl")
    with open(p, "w") as fh:
        for m in _gen(seed):
            fh.write(json.dumps(m) + "\\n")
    return p


def _cfg_dir(cfg):
    d = tempfile.mkdtemp(prefix="cfg-", dir="/tmp")
    with open(os.path.join(d, "config.json"), "w") as fh:
        json.dump(cfg, fh)
    return d


def _env(cfg):
    e = dict(os.environ)
    e["KVD_HOME"] = _cfg_dir(cfg)
    return e


def _reference_bytes(trace, cfg):
    d = _cfg_dir(cfg)
    out = os.path.join(d, "out")
    ck = os.path.join(d, "ck")
    old = os.environ.get("KVD_HOME")
    os.environ["KVD_HOME"] = d
    try:
        _REFNS["run"](trace, out, ck, False, True)
    finally:
        if old is None:
            os.environ.pop("KVD_HOME", None)
        else:
            os.environ["KVD_HOME"] = old
    with open(out, "rb") as fh:
        return fh.read()


def _total(trace):
    n = 0
    for ln in open(trace):
        if ln.strip():
            n += 1
    return n


def _clean(trace, env):
    d = tempfile.mkdtemp(prefix="run-", dir="/tmp")
    out = os.path.join(d, "out")
    ck = os.path.join(d, "ck")
    subprocess.run([STREAM, "run", trace, out, ck, "--final"], env=env, capture_output=True, timeout=600)
    data = open(out, "rb").read() if os.path.exists(out) else b""
    return data, out, ck


def _crash(trace, env, boundaries):
    lines = [ln.strip() for ln in open(trace) if ln.strip()]
    shutil.rmtree(os.path.dirname(trace), ignore_errors=True)
    work = tempfile.mkdtemp(prefix="work-", dir="/tmp")
    out = os.path.join(work, "out")
    ck = os.path.join(work, "ck")
    bounds = [0] + list(boundaries) + [len(lines)]
    chunks = [lines[bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]
    for i, chunk in enumerate(chunks):
        cd = tempfile.mkdtemp(prefix="chunk-", dir="/tmp")
        cf = os.path.join(cd, "chunk")
        with open(cf, "w") as fh:
            fh.write("\\n".join(chunk) + ("\\n" if chunk else ""))
        args = [STREAM, "run", cf, out, ck]
        if i > 0:
            args.append("--resume")
        if i == len(chunks) - 1:
            args.append("--final")
        subprocess.run(args, env=env, capture_output=True, timeout=600)
        shutil.rmtree(cd, ignore_errors=True)
    data = open(out, "rb").read() if os.path.exists(out) else b""
    return data, out, ck


def _records(data, typ):
    rows = []
    for ln in data.decode().splitlines():
        o = json.loads(ln)
        if o.get("type") == typ:
            rows.append((o["key"], o["start"], o["end"], o["count"], o["sum"]))
    return rows


def _dropped(data):
    for ln in data.decode().splitlines():
        o = json.loads(ln)
        if o.get("type") == "EOF":
            return o["dropped_late"]
    return None


@criterion
def c1_clean_bytes(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    return got == _reference_bytes(tr, CFG1)


@criterion
def c2_crash_bytes(workspace: Path) -> bool:
    tr = _write_trace(CRASH2)
    ref = _reference_bytes(tr, CFG1)
    got, _, _ = _crash(tr, _env(CFG1), [_total(tr) // 2])
    return got == ref


@criterion
def c3_dropped_count(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    return _dropped(got) == _dropped(_reference_bytes(tr, CFG1))


@criterion
def c4_atomic_no_tmp(workspace: Path) -> bool:
    tr = _write_trace(CRASH4)
    got, out, ck = _crash(tr, _env(CFG1), [_total(tr) // 2])
    if os.path.exists(ck + ".tmp"):
        return False
    try:
        for ln in got.decode().splitlines():
            json.loads(ln)
    except Exception:
        return False
    return len(got) > 0


@criterion
def c5_clean_config2(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG2))
    return got == _reference_bytes(tr, CFG2)


@criterion
def c6_retract_records(workspace: Path) -> bool:
    tr = _write_trace(RETRACT_SEED)
    got, _, _ = _clean(tr, _env(CFG1))
    return _records(got, "RETRACT") == _records(_reference_bytes(tr, CFG1), "RETRACT")


@criterion
def c7_final_records(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    return _records(got, "FINAL") == _records(_reference_bytes(tr, CFG1), "FINAL")


@criterion
def c8_double_crash(workspace: Path) -> bool:
    tr = _write_trace(CRASH8)
    ref = _reference_bytes(tr, CFG1)
    n = _total(tr)
    got, _, _ = _crash(tr, _env(CFG1), [n // 3, 2 * n // 3])
    return got == ref


@criterion
def c9_session_boundaries(workspace: Path) -> bool:
    tr = _write_trace(BRIDGE_SEED)
    got, _, _ = _clean(tr, _env(CFG1))
    ref = _reference_bytes(tr, CFG1)
    g = set((k, s, e) for (k, s, e, c, su) in _records(got, "FINAL"))
    r = set((k, s, e) for (k, s, e, c, su) in _records(ref, "FINAL"))
    return g == r


@criterion
def c10_crash_config2(workspace: Path) -> bool:
    tr = _write_trace(CRASH10)
    ref = _reference_bytes(tr, CFG2)
    got, _, _ = _crash(tr, _env(CFG2), [_total(tr) // 2])
    return got == ref


@criterion
def c11_json_sorted(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    lines = got.decode().splitlines()
    if not lines:
        return False
    for ln in lines:
        try:
            o = json.loads(ln)
        except Exception:
            return False
        if json.dumps(o, sort_keys=True) != ln:
            return False
    return True


@criterion
def c12_emit_contiguous(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    try:
        ids = [json.loads(ln)["emit"] for ln in got.decode().splitlines()]
    except Exception:
        return False
    return ids == list(range(1, len(ids) + 1)) and len(ids) > 0


@criterion
def c13_determinism(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    a, _, _ = _clean(tr, _env(CFG1))
    b, _, _ = _clean(tr, _env(CFG1))
    return a == b and len(a) > 0


@criterion
def c14_crash_before_ckpt(workspace: Path) -> bool:
    tr = _write_trace(CRASH14)
    ref = _reference_bytes(tr, CFG1)
    got, _, _ = _crash(tr, _env(CFG1), [1])
    return got == ref


@criterion
def c15_single_eof(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    got, _, _ = _clean(tr, _env(CFG1))
    objs = [json.loads(ln) for ln in got.decode().splitlines()]
    if not objs:
        return False
    eofs = [o for o in objs if o.get("type") == "EOF"]
    return len(eofs) == 1 and objs[-1].get("type") == "EOF"


import rewardkit as rk
''' % {"c1": c1, "c2": c2, "ref": _reference_src(), "gen": _GEN_SRC}
    reg = "".join("rk.{n}(weight={w})\n".format(n=_CNAMES[it["id"]], w=it["weight"]) for it in g["compiled_rubric"])
    return header + body + reg


def _judge_toml(g):
    j = g["judge"]
    files = "[" + ", ".join('"%s"' % f for f in j["files"]) + "]"
    out = ["# " + GEN, "[judge]",
           'judge = "{}"'.format(j["backend"]),
           'model = "{}"'.format(j["model"]),
           'version = "{}"'.format(j["version"]),
           "files = " + files,
           'mode = "{}"'.format(j["mode"]),
           "isolated = {}".format("true" if j["isolated"] else "false"),
           'cwd = "{}"'.format(j["cwd"]),
           'reasoning_effort = "{}"'.format(j["reasoning_effort"]),
           "timeout = {}".format(int(j["timeout"])),
           'guard = "{}"'.format(j["guard"]),
           "",
           "[scoring]", 'aggregation = "weighted-mean"', ""]
    for it in g["judged_rubric"]:
        out += ["[[criterion]]", 'id = "{i}"'.format(i=it["id"]),
                'description = "{d}"'.format(d=it["criterion"].replace('"', "'")),
                'type = "binary"', "weight = {w}".format(w=it["weight"]),
                "[criterion.annotations]", 'dimension = "{d}"'.format(d=it["dimension"]),
                'mode = "judged"', ""]
    return "\n".join(out) + "\n"


def _write(path, text, mode=0o644):
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, mode)


def _assert_judge_timeout(g):
    import tomllib
    with open(os.path.join(BUNDLE, "task.toml"), "rb") as fh:
        vts = tomllib.load(fh)["verifier"]["timeout_sec"]
    jt = int(g["judge"]["timeout"])
    if not jt < vts:
        raise SystemExit("invariant violated: judge.timeout (%d) must be < verifier.timeout_sec (%s)" % (jt, vts))


def main(argv):
    g = _grounding()
    _assert_judge_timeout(g)
    targets = {
        os.path.join(HERE, "solve.sh"): (_solve_sh(), 0o755),
        os.path.join(HERE, "TRUTH.md"): (_truth_md(g), 0o644),
        os.path.join(BUNDLE, "tests", "test_output.py"): (_test_output_py(g), 0o644),
        os.path.join(BUNDLE, "tests", "judge.toml"): (_judge_toml(g), 0o644),
    }
    check = "--check" in argv
    drift = []
    for path, (text, mode) in targets.items():
        if check:
            cur = open(path).read() if os.path.exists(path) else None
            if cur != text:
                drift.append(os.path.relpath(path, BUNDLE))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, text, mode)
    if check and drift:
        sys.stderr.write("regeneration drift: %s\n" % ", ".join(sorted(drift)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
