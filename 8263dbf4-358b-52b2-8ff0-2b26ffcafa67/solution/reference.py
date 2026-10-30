#!/usr/bin/env python3
"""Reference stateful-streaming session-window engine (slot 4).

Deterministic, single-threaded. Time advances only through watermark messages;
there is no wall-clock dependence anywhere. The stream is delivered across one or
more process invocations (chunks). Each invocation processes exactly the messages
in its own chunk file, maintaining per-key gap-based session windows and emitting
FINAL aggregates when a window closes, RETRACT + re-FINAL when a late event within
allowed lateness bridges already-finalized sessions. A non-final invocation
persists its full state to the checkpoint atomically (temp then rename) and exits;
a --resume invocation restores that state, appends to the existing output, and
continues. Only the --final invocation flushes all remaining windows and writes
the EOF record. Because a resume invocation is handed ONLY the unconsumed suffix
of the stream, the pre-crash window state cannot be recomputed and must be
restored from the checkpoint; the concatenated output equals a single-process run.

Config (JSON at $KVD_HOME/config.json, default /app/data/config.json):
  session_gap_ms      : two events for a key are in the same session when their
                        timestamps are within this gap; a session [start,end]
                        absorbs an event with start-gap <= ts <= end+gap.
  allowed_lateness_ms : a late event is processed when wm - ts <= this value,
                        otherwise it is dropped and counted.
  checkpoint_interval : advisory durability cadence (chunk boundaries are the
                        resume points in this harness).

CLI:  stream run <chunk> <out> <ckpt> [--resume] [--final]

Output file: one JSON object per line (keys sorted), each an emission record:
  {"count":C,"emit":E,"end":EN,"key":K,"start":S,"sum":SUM,"type":"FINAL"|"RETRACT"}
terminated by {"dropped_late":D,"emit":E,"type":"EOF"}. `emit` is a 1-based gap
free monotone counter that must persist across chunks: the exactly-once contract
is that the chunked (crash/resume) output is byte-identical to a single run.
"""
import json
import os
import sys

NEG_INF = -(10 ** 18)
POS_INF = 10 ** 18


def _config():
    cfg = os.path.join(os.environ.get("KVD_HOME", "/app/data"), "config.json")
    with open(cfg) as fh:
        c = json.load(fh)
    return int(c["session_gap_ms"]), int(c["allowed_lateness_ms"]), int(c["checkpoint_interval"])


def _rec_sort_key(r):
    # canonical order within one emission batch: key, start, end, then RETRACT before FINAL
    rank = 0 if r["type"] == "RETRACT" else 1
    return (r["key"], r["start"], r["end"], rank)


class Engine:
    def __init__(self, gap, lateness, out_path):
        self.gap = gap
        self.lateness = lateness
        self.out_path = out_path
        self.wm = NEG_INF
        self.emit = 0
        self.dropped = 0
        self.open = {}        # key -> list of sessions {start,end,count,sum}
        self.final = {}       # key -> list of finalized-but-retractable sessions
        self._out = None

    # ---- serialization ----
    def state(self):
        return {
            "wm": self.wm, "emit": self.emit, "dropped": self.dropped,
            "open": self.open, "final": self.final,
        }

    def load(self, st):
        self.wm = st["wm"]
        self.emit = st["emit"]
        self.dropped = st["dropped"]
        self.open = {k: [dict(s) for s in v] for k, v in st["open"].items()}
        self.final = {k: [dict(s) for s in v] for k, v in st["final"].items()}

    # ---- output ----
    def _append(self, records):
        # assign emit ids in canonical order and append as JSON lines
        for r in sorted(records, key=_rec_sort_key):
            self.emit += 1
            r["emit"] = self.emit
            self._out.write(json.dumps(r, sort_keys=True) + "\n")
        self._out.flush()

    # ---- window mechanics ----
    def _within(self, s, ts):
        return s["start"] - self.gap <= ts <= s["end"] + self.gap

    def _merge(self, sessions, ts, val):
        start = min([s["start"] for s in sessions] + [ts])
        end = max([s["end"] for s in sessions] + [ts])
        count = sum(s["count"] for s in sessions) + 1
        total = sum(s["sum"] for s in sessions) + val
        return {"start": start, "end": end, "count": count, "sum": total}

    def _final_record(self, key, s, rtype):
        return {"type": rtype, "key": key, "start": s["start"],
                "end": s["end"], "count": s["count"], "sum": s["sum"]}

    def on_event(self, key, ts, val):
        # drop if too late relative to the current watermark
        if self.wm - ts > self.lateness:
            self.dropped += 1
            return
        open_k = self.open.get(key, [])
        final_k = self.final.get(key, [])
        hit_open = [s for s in open_k if self._within(s, ts)]
        hit_final = [s for s in final_k if self._within(s, ts)]
        batch = []
        # any finalized session the event touches must be retracted and merged
        for s in hit_final:
            batch.append(self._final_record(key, s, "RETRACT"))
        self.open[key] = [s for s in open_k if s not in hit_open]
        self.final[key] = [s for s in final_k if s not in hit_final]
        merged = self._merge(hit_open + hit_final, ts, val)
        # if the watermark has already passed the merged window close, re-finalize now
        if self.wm > merged["end"] + self.gap:
            batch.append(self._final_record(key, merged, "FINAL"))
            self.final.setdefault(key, []).append(merged)
        else:
            self.open.setdefault(key, []).append(merged)
        if batch:
            self._append(batch)

    def on_watermark(self, ts):
        if ts > self.wm:
            self.wm = ts
        batch = []
        for key in list(self.open.keys()):
            keep = []
            for s in self.open[key]:
                if self.wm > s["end"] + self.gap:
                    batch.append(self._final_record(key, s, "FINAL"))
                    self.final.setdefault(key, []).append(s)
                else:
                    keep.append(s)
            self.open[key] = keep
        # garbage-collect finalized sessions no late event can ever reach again
        for key in list(self.final.keys()):
            self.final[key] = [s for s in self.final[key]
                               if not (self.wm > s["end"] + self.gap + self.lateness)]
        if batch:
            self._append(batch)

    def finish(self):
        # flush every remaining open session at +inf, then the EOF record
        self.wm = POS_INF
        batch = []
        for key in list(self.open.keys()):
            for s in self.open[key]:
                batch.append(self._final_record(key, s, "FINAL"))
            self.open[key] = []
        if batch:
            self._append(batch)
        self.emit += 1
        self._out.write(json.dumps({"type": "EOF", "emit": self.emit,
                                    "dropped_late": self.dropped}, sort_keys=True) + "\n")
        self._out.flush()


def _checkpoint(ckpt_path, engine):
    tmp = ckpt_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(engine.state(), fh, sort_keys=True)
        fh.flush()
    os.replace(tmp, ckpt_path)  # atomic temp-then-rename


def run(trace, out_path, ckpt_path, resume, final):
    gap, lateness, interval = _config()
    eng = Engine(gap, lateness, out_path)
    if resume and os.path.exists(ckpt_path):
        with open(ckpt_path) as fh:
            eng.load(json.load(fh))
        eng._out = open(out_path, "a")
    else:
        eng._out = open(out_path, "w")
    with open(trace) as fh:
        lines = fh.readlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg["type"] == "event":
            eng.on_event(msg["key"], int(msg["ts"]), int(msg["val"]))
            sys.stdout.write("ACK %d\n" % int(msg["seq"]))
            sys.stdout.flush()
        elif msg["type"] == "watermark":
            eng.on_watermark(int(msg["ts"]))
    if final:
        eng.finish()
    else:
        _checkpoint(ckpt_path, eng)
    eng._out.close()
    return 0


def main(argv):
    if len(argv) >= 4 and argv[0] == "run":
        resume = "--resume" in argv[4:]
        final = "--final" in argv[4:]
        return run(argv[1], argv[2], argv[3], resume, final)
    sys.stderr.write("usage: stream run <chunk> <out> <ckpt> [--resume] [--final]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
