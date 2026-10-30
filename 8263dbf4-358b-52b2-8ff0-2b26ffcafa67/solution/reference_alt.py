#!/usr/bin/env python3
"""Independent alternate-correct streaming engine (slot 4 cross-check).

Same observable contract as solution/reference.py but a deliberately different
internal architecture: sessions are held in a single global list kept sorted by
(key, start) and candidate windows for an event are found by a bisect range scan
over that sorted index rather than by a per-key linear scan; emission is a single
pass that sorts a collected batch. Its checkpoint format is its own. The ONLY
guarantee it shares with the reference is byte-identical output (single run, and
chunked crash/resume), which is what proves the output is determined by the spec,
not by one implementation's structure.

CLI:  stream run <chunk> <out> <ckpt> [--resume] [--final]
"""
import bisect
import json
import os
import sys

NEG_INF = -(10 ** 18)
POS_INF = 10 ** 18


def _cfg():
    cfg = os.path.join(os.environ.get("KVD_HOME", "/app/data"), "config.json")
    with open(cfg) as fh:
        c = json.load(fh)
    return int(c["session_gap_ms"]), int(c["allowed_lateness_ms"]), int(c["checkpoint_interval"])


def _canon(r):
    return (r["key"], r["start"], r["end"], 0 if r["type"] == "RETRACT" else 1)


class Alt:
    def __init__(self, gap, lateness):
        self.gap = gap
        self.lat = lateness
        self.wm = NEG_INF
        self.emit = 0
        self.dropped = 0
        # sessions: list of dicts with key,start,end,count,sum,final(bool); kept sorted by (key,start)
        self.sessions = []
        self.out = None

    # ---- state ----
    def snapshot(self):
        return {"wm": self.wm, "emit": self.emit, "dropped": self.dropped,
                "sessions": self.sessions}

    def restore(self, st):
        self.wm = st["wm"]; self.emit = st["emit"]; self.dropped = st["dropped"]
        self.sessions = [dict(s) for s in st["sessions"]]

    # ---- output ----
    def flush(self, batch):
        for r in sorted(batch, key=_canon):
            self.emit += 1
            r["emit"] = self.emit
            self.out.write(json.dumps(r, sort_keys=True) + "\n")
        self.out.flush()

    def _keys(self):
        return [(s["key"], s["start"]) for s in self.sessions]

    def _rec(self, s, rtype):
        return {"type": rtype, "key": s["key"], "start": s["start"],
                "end": s["end"], "count": s["count"], "sum": s["sum"]}

    def event(self, key, ts, val):
        if self.wm - ts > self.lat:
            self.dropped += 1
            return
        # bisect the sorted index to the block of sessions for this key
        idx = self._keys()
        lo = bisect.bisect_left(idx, (key, NEG_INF))
        hi = bisect.bisect_right(idx, (key, POS_INF))
        touched = []
        for i in range(lo, hi):
            s = self.sessions[i]
            if s["start"] - self.gap <= ts <= s["end"] + self.gap:
                touched.append(i)
        batch = []
        for i in touched:
            if self.sessions[i]["final"]:
                batch.append(self._rec(self.sessions[i], "RETRACT"))
        merged = {"key": key, "start": ts, "end": ts, "count": 1, "sum": val, "final": False}
        for i in touched:
            s = self.sessions[i]
            merged["start"] = min(merged["start"], s["start"])
            merged["end"] = max(merged["end"], s["end"])
            merged["count"] += s["count"]
            merged["sum"] += s["sum"]
        for i in sorted(touched, reverse=True):
            del self.sessions[i]
        if self.wm > merged["end"] + self.gap:
            merged["final"] = True
            batch.append(self._rec(merged, "FINAL"))
        self._insert(merged)
        if batch:
            self.flush(batch)

    def _insert(self, s):
        k = (s["key"], s["start"])
        bisect.insort(self.sessions, s, key=lambda x: (x["key"], x["start"]))

    def watermark(self, ts):
        if ts > self.wm:
            self.wm = ts
        batch = []
        survivors = []
        for s in self.sessions:
            if not s["final"] and self.wm > s["end"] + self.gap:
                s["final"] = True
                batch.append(self._rec(s, "FINAL"))
            # GC: drop finalized sessions beyond reach of any allowed-late event
            if s["final"] and self.wm > s["end"] + self.gap + self.lat:
                continue
            survivors.append(s)
        self.sessions = survivors
        if batch:
            self.flush(batch)

    def finish(self):
        self.wm = POS_INF
        batch = [self._rec(s, "FINAL") for s in self.sessions if not s["final"]]
        self.sessions = []
        if batch:
            self.flush(batch)
        self.emit += 1
        self.out.write(json.dumps({"type": "EOF", "emit": self.emit,
                                   "dropped_late": self.dropped}, sort_keys=True) + "\n")
        self.out.flush()


def _ckpt(path, eng):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(eng.snapshot(), fh, sort_keys=True)
        fh.flush()
    os.replace(tmp, path)


def run(trace, out_path, ckpt, resume, final):
    gap, lat, interval = _cfg()
    eng = Alt(gap, lat)
    if resume and os.path.exists(ckpt):
        with open(ckpt) as fh:
            eng.restore(json.load(fh))
        eng.out = open(out_path, "a")
    else:
        eng.out = open(out_path, "w")
    with open(trace) as fh:
        rows = fh.readlines()
    for raw in rows:
        line = raw.strip()
        if not line:
            continue
        m = json.loads(line)
        if m["type"] == "event":
            eng.event(m["key"], int(m["ts"]), int(m["val"]))
            sys.stdout.write("ACK %d\n" % int(m["seq"])); sys.stdout.flush()
        elif m["type"] == "watermark":
            eng.watermark(int(m["ts"]))
    if final:
        eng.finish()
    else:
        _ckpt(ckpt, eng)
    eng.out.close()
    return 0


def main(argv):
    if len(argv) >= 4 and argv[0] == "run":
        return run(argv[1], argv[2], argv[3], "--resume" in argv[4:], "--final" in argv[4:])
    sys.stderr.write("usage: stream run <chunk> <out> <ckpt> [--resume] [--final]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
