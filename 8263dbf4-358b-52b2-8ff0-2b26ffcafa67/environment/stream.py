#!/usr/bin/env python3
"""Starter skeleton for /app/stream (INCOMPLETE).

This stub establishes the CLI, reads the config, parses the JSONL trace, and
prints `ACK <seq>` per event, then writes a terminating EOF record. It does NOT
implement session windows, finalization, late-event retraction, the dropped-late
count, atomic checkpointing, or exactly-once --resume. Implement those so the
output matches the behavioral contract in instruction.md.

CLI:  stream run <trace> <out> <ckpt> [--resume]
"""
import json
import os
import sys

CFG = os.path.join(os.environ.get("KVD_HOME", "/app/data"), "config.json")


def _config():
    with open(CFG) as fh:
        c = json.load(fh)
    return int(c["session_gap_ms"]), int(c["allowed_lateness_ms"]), int(c["checkpoint_interval"])


def run(trace, out_path, ckpt_path, resume, final):
    gap, lateness, interval = _config()
    emit = 0
    # TODO: on --resume, restore full window state from the checkpoint and append to
    # the existing output (this invocation's <trace> is ONLY the unconsumed suffix,
    # so earlier messages cannot be re-read); otherwise start a fresh output.
    out = open(out_path, "w")
    with open(trace) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg["type"] == "event":
                # TODO: maintain per-key gap session windows; finalize on watermark;
                # retract+re-final on bridging late events; drop+count over-late events.
                sys.stdout.write("ACK %d\n" % int(msg["seq"]))
                sys.stdout.flush()
            elif msg["type"] == "watermark":
                # TODO: finalize and garbage-collect sessions the watermark has passed.
                pass
    # TODO: if not --final, persist full state atomically and exit WITHOUT an EOF; if
    # --final, flush remaining windows and write the terminating EOF. Keep the emit
    # counter monotonic across chunks.
    emit += 1
    out.write(json.dumps({"type": "EOF", "emit": emit, "dropped_late": 0}, sort_keys=True) + "\n")
    out.flush()
    out.close()
    return 0


def main(argv):
    if len(argv) >= 4 and argv[0] == "run":
        return run(argv[1], argv[2], argv[3], "--resume" in argv[4:], "--final" in argv[4:])
    sys.stderr.write("usage: stream run <chunk> <out> <ckpt> [--resume] [--final]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
