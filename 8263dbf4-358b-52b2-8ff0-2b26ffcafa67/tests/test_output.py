# GENERATED SECTION. DO NOT HAND-EDIT.
"""Compiled Reward Kit criteria for the exactly-once session-window task.

The reference engine is embedded verbatim from solution/reference.py and run
in-process to produce the expected output; the agent's /app/stream is run as a
subprocess and compared byte for byte, clean and across a deterministic
chunked restarts (--resume/--final), over seeded traces and two field configs.
"""
import json
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
CFG1 = {'session_gap_ms': 30, 'allowed_lateness_ms': 60, 'checkpoint_interval': 7}
CFG2 = {'session_gap_ms': 50, 'allowed_lateness_ms': 100, 'checkpoint_interval': 5}

_REF_SRC = '#!/usr/bin/env python3\n"""Reference stateful-streaming session-window engine (slot 4).\n\nDeterministic, single-threaded. Time advances only through watermark messages;\nthere is no wall-clock dependence anywhere. The stream is delivered across one or\nmore process invocations (chunks). Each invocation processes exactly the messages\nin its own chunk file, maintaining per-key gap-based session windows and emitting\nFINAL aggregates when a window closes, RETRACT + re-FINAL when a late event within\nallowed lateness bridges already-finalized sessions. A non-final invocation\npersists its full state to the checkpoint atomically (temp then rename) and exits;\na --resume invocation restores that state, appends to the existing output, and\ncontinues. Only the --final invocation flushes all remaining windows and writes\nthe EOF record. Because a resume invocation is handed ONLY the unconsumed suffix\nof the stream, the pre-crash window state cannot be recomputed and must be\nrestored from the checkpoint; the concatenated output equals a single-process run.\n\nConfig (JSON at $KVD_HOME/config.json, default /app/data/config.json):\n  session_gap_ms      : two events for a key are in the same session when their\n                        timestamps are within this gap; a session [start,end]\n                        absorbs an event with start-gap <= ts <= end+gap.\n  allowed_lateness_ms : a late event is processed when wm - ts <= this value,\n                        otherwise it is dropped and counted.\n  checkpoint_interval : advisory durability cadence (chunk boundaries are the\n                        resume points in this harness).\n\nCLI:  stream run <chunk> <out> <ckpt> [--resume] [--final]\n\nOutput file: one JSON object per line (keys sorted), each an emission record:\n  {"count":C,"emit":E,"end":EN,"key":K,"start":S,"sum":SUM,"type":"FINAL"|"RETRACT"}\nterminated by {"dropped_late":D,"emit":E,"type":"EOF"}. `emit` is a 1-based gap\nfree monotone counter that must persist across chunks: the exactly-once contract\nis that the chunked (crash/resume) output is byte-identical to a single run.\n"""\nimport json\nimport os\nimport sys\n\nNEG_INF = -(10 ** 18)\nPOS_INF = 10 ** 18\n\n\ndef _config():\n    cfg = os.path.join(os.environ.get("KVD_HOME", "/app/data"), "config.json")\n    with open(cfg) as fh:\n        c = json.load(fh)\n    return int(c["session_gap_ms"]), int(c["allowed_lateness_ms"]), int(c["checkpoint_interval"])\n\n\ndef _rec_sort_key(r):\n    # canonical order within one emission batch: key, start, end, then RETRACT before FINAL\n    rank = 0 if r["type"] == "RETRACT" else 1\n    return (r["key"], r["start"], r["end"], rank)\n\n\nclass Engine:\n    def __init__(self, gap, lateness, out_path):\n        self.gap = gap\n        self.lateness = lateness\n        self.out_path = out_path\n        self.wm = NEG_INF\n        self.emit = 0\n        self.dropped = 0\n        self.open = {}        # key -> list of sessions {start,end,count,sum}\n        self.final = {}       # key -> list of finalized-but-retractable sessions\n        self._out = None\n\n    # ---- serialization ----\n    def state(self):\n        return {\n            "wm": self.wm, "emit": self.emit, "dropped": self.dropped,\n            "open": self.open, "final": self.final,\n        }\n\n    def load(self, st):\n        self.wm = st["wm"]\n        self.emit = st["emit"]\n        self.dropped = st["dropped"]\n        self.open = {k: [dict(s) for s in v] for k, v in st["open"].items()}\n        self.final = {k: [dict(s) for s in v] for k, v in st["final"].items()}\n\n    # ---- output ----\n    def _append(self, records):\n        # assign emit ids in canonical order and append as JSON lines\n        for r in sorted(records, key=_rec_sort_key):\n            self.emit += 1\n            r["emit"] = self.emit\n            self._out.write(json.dumps(r, sort_keys=True) + "\\n")\n        self._out.flush()\n\n    # ---- window mechanics ----\n    def _within(self, s, ts):\n        return s["start"] - self.gap <= ts <= s["end"] + self.gap\n\n    def _merge(self, sessions, ts, val):\n        start = min([s["start"] for s in sessions] + [ts])\n        end = max([s["end"] for s in sessions] + [ts])\n        count = sum(s["count"] for s in sessions) + 1\n        total = sum(s["sum"] for s in sessions) + val\n        return {"start": start, "end": end, "count": count, "sum": total}\n\n    def _final_record(self, key, s, rtype):\n        return {"type": rtype, "key": key, "start": s["start"],\n                "end": s["end"], "count": s["count"], "sum": s["sum"]}\n\n    def on_event(self, key, ts, val):\n        # drop if too late relative to the current watermark\n        if self.wm - ts > self.lateness:\n            self.dropped += 1\n            return\n        open_k = self.open.get(key, [])\n        final_k = self.final.get(key, [])\n        hit_open = [s for s in open_k if self._within(s, ts)]\n        hit_final = [s for s in final_k if self._within(s, ts)]\n        batch = []\n        # any finalized session the event touches must be retracted and merged\n        for s in hit_final:\n            batch.append(self._final_record(key, s, "RETRACT"))\n        self.open[key] = [s for s in open_k if s not in hit_open]\n        self.final[key] = [s for s in final_k if s not in hit_final]\n        merged = self._merge(hit_open + hit_final, ts, val)\n        # if the watermark has already passed the merged window close, re-finalize now\n        if self.wm > merged["end"] + self.gap:\n            batch.append(self._final_record(key, merged, "FINAL"))\n            self.final.setdefault(key, []).append(merged)\n        else:\n            self.open.setdefault(key, []).append(merged)\n        if batch:\n            self._append(batch)\n\n    def on_watermark(self, ts):\n        if ts > self.wm:\n            self.wm = ts\n        batch = []\n        for key in list(self.open.keys()):\n            keep = []\n            for s in self.open[key]:\n                if self.wm > s["end"] + self.gap:\n                    batch.append(self._final_record(key, s, "FINAL"))\n                    self.final.setdefault(key, []).append(s)\n                else:\n                    keep.append(s)\n            self.open[key] = keep\n        # garbage-collect finalized sessions no late event can ever reach again\n        for key in list(self.final.keys()):\n            self.final[key] = [s for s in self.final[key]\n                               if not (self.wm > s["end"] + self.gap + self.lateness)]\n        if batch:\n            self._append(batch)\n\n    def finish(self):\n        # flush every remaining open session at +inf, then the EOF record\n        self.wm = POS_INF\n        batch = []\n        for key in list(self.open.keys()):\n            for s in self.open[key]:\n                batch.append(self._final_record(key, s, "FINAL"))\n            self.open[key] = []\n        if batch:\n            self._append(batch)\n        self.emit += 1\n        self._out.write(json.dumps({"type": "EOF", "emit": self.emit,\n                                    "dropped_late": self.dropped}, sort_keys=True) + "\\n")\n        self._out.flush()\n\n\ndef _checkpoint(ckpt_path, engine):\n    tmp = ckpt_path + ".tmp"\n    with open(tmp, "w") as fh:\n        json.dump(engine.state(), fh, sort_keys=True)\n        fh.flush()\n    os.replace(tmp, ckpt_path)  # atomic temp-then-rename\n\n\ndef run(trace, out_path, ckpt_path, resume, final):\n    gap, lateness, interval = _config()\n    eng = Engine(gap, lateness, out_path)\n    if resume and os.path.exists(ckpt_path):\n        with open(ckpt_path) as fh:\n            eng.load(json.load(fh))\n        eng._out = open(out_path, "a")\n    else:\n        eng._out = open(out_path, "w")\n    with open(trace) as fh:\n        lines = fh.readlines()\n    for raw in lines:\n        line = raw.strip()\n        if not line:\n            continue\n        msg = json.loads(line)\n        if msg["type"] == "event":\n            eng.on_event(msg["key"], int(msg["ts"]), int(msg["val"]))\n            sys.stdout.write("ACK %d\\n" % int(msg["seq"]))\n            sys.stdout.flush()\n        elif msg["type"] == "watermark":\n            eng.on_watermark(int(msg["ts"]))\n    if final:\n        eng.finish()\n    else:\n        _checkpoint(ckpt_path, eng)\n    eng._out.close()\n    return 0\n\n\ndef main(argv):\n    if len(argv) >= 4 and argv[0] == "run":\n        resume = "--resume" in argv[4:]\n        final = "--final" in argv[4:]\n        return run(argv[1], argv[2], argv[3], resume, final)\n    sys.stderr.write("usage: stream run <chunk> <out> <ckpt> [--resume] [--final]\\n")\n    return 2\n\n\nif __name__ == "__main__":\n    sys.exit(main(sys.argv[1:]))\n'
_REFNS = {}
exec(compile(_REF_SRC, "reference_embedded", "exec"), _REFNS)


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


def _write_trace(seed):
    d = tempfile.mkdtemp(prefix="trace-", dir="/tmp")
    p = os.path.join(d, "trace.jsonl")
    with open(p, "w") as fh:
        for m in _gen(seed):
            fh.write(json.dumps(m) + "\n")
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


def _clean_cap(trace, env):
    d = tempfile.mkdtemp(prefix="run-", dir="/tmp")
    out = os.path.join(d, "out")
    ck = os.path.join(d, "ck")
    r = subprocess.run([STREAM, "run", trace, out, ck, "--final"], env=env, capture_output=True, timeout=600)
    return r.stdout.decode("utf-8", "replace"), r.returncode


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
            fh.write("\n".join(chunk) + ("\n" if chunk else ""))
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
    ref = _reference_bytes(tr, CFG1)
    got, out, ck = _crash(tr, _env(CFG1), [_total(tr) // 2])
    if got != ref:
        return False
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
    if got != _reference_bytes(tr, CFG1):
        return False
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
    if got != _reference_bytes(tr, CFG1):
        return False
    try:
        ids = [json.loads(ln)["emit"] for ln in got.decode().splitlines()]
    except Exception:
        return False
    return ids == list(range(1, len(ids) + 1)) and len(ids) > 0


@criterion
def c13_determinism(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    ref = _reference_bytes(tr, CFG1)
    a, _, _ = _clean(tr, _env(CFG1))
    b, _, _ = _clean(tr, _env(CFG1))
    return a == b and a == ref and len(a) > 0


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
    if got != _reference_bytes(tr, CFG1):
        return False
    objs = [json.loads(ln) for ln in got.decode().splitlines()]
    if not objs:
        return False
    eofs = [o for o in objs if o.get("type") == "EOF"]
    return len(eofs) == 1 and objs[-1].get("type") == "EOF"


@criterion
def c16_ack_stream(workspace: Path) -> bool:
    tr = _write_trace(PRIMARY)
    so, _ = _clean_cap(tr, _env(CFG1))
    expected = ["ACK %d" % int(json.loads(l)["seq"])
                for l in open(tr) if l.strip() and json.loads(l)["type"] == "event"]
    return [x for x in so.splitlines() if x.strip()] == expected


@criterion
def c17_usage_exit2(workspace: Path) -> bool:
    r = subprocess.run([STREAM, "run"], env=_env(CFG1), capture_output=True, timeout=60)
    return r.returncode == 2


import rewardkit as rk
rk.c1_clean_bytes(weight=5)
rk.c2_crash_bytes(weight=5)
rk.c3_dropped_count(weight=3)
rk.c4_atomic_no_tmp(weight=3)
rk.c5_clean_config2(weight=3)
rk.c6_retract_records(weight=3)
rk.c7_final_records(weight=3)
rk.c8_double_crash(weight=3)
rk.c9_session_boundaries(weight=3)
rk.c10_crash_config2(weight=3)
rk.c11_json_sorted(weight=1)
rk.c12_emit_contiguous(weight=1)
rk.c13_determinism(weight=1)
rk.c14_crash_before_ckpt(weight=1)
rk.c15_single_eof(weight=1)
rk.c16_ack_stream(weight=1)
rk.c17_usage_exit2(weight=1)
