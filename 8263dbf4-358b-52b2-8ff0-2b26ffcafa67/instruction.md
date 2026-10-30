# Implement an exactly-once session-window streaming engine

## Overview

Build a single-threaded, deterministic command-line engine at `/app/stream` that
consumes a fixed trace of streaming messages, maintains per-key **gap session
windows**, emits **FINAL** aggregates as windows close, **RETRACT**s and
re-finalizes when a late event bridges already-finalized windows, and survives
being restarted mid-stream — producing **bit-identical, exactly-once** output by
checkpointing and restoring its state across process restarts.

Determinism is mandatory. Logical time advances **only** through watermark
messages; your program must never consult the wall clock, the system time, a
random source, or any process/network state. Running the same stream twice, or
running it split across any number of restart (`--resume`) boundaries, must
produce the identical output file byte for byte.

A starter skeleton is at `/app/stream` (it only ACKs events and writes an EOF
record). Replace it with a correct engine.

## Configuration

Read these integers from `config.json` in the directory named by the `KVD_HOME`
environment variable, defaulting to `/app/data/config.json` when `KVD_HOME` is
unset (the shipped file lives at `/app/data/config.json`):

```json
{"session_gap_ms": 30, "allowed_lateness_ms": 60, "checkpoint_interval": 7}
```

- `session_gap_ms` (the **gap**): how close in time two of a key's events must be
  to belong to the same session.
- `allowed_lateness_ms` (the **lateness**): how far a late event may trail the
  watermark and still be applied.
- `checkpoint_interval`: advisory durability cadence; the resume points enforced
  by the harness are the chunk boundaries between invocations.

Do not hard-code these; a second evaluation uses different values.

## Command-line interface

```
stream run <chunk> <out> <ckpt>                     # first chunk, more to follow
stream run <chunk> <out> <ckpt> --final             # first chunk, also the last
stream run <chunk> <out> <ckpt> --resume            # continue, more to follow
stream run <chunk> <out> <ckpt> --resume --final    # continue, and this is the last chunk
```

`<chunk>` is a JSONL file holding the messages for **this invocation only**,
`<out>` is the output JSONL file, `<ckpt>` is the checkpoint file. A usage error
or missing argument exits `2`. See "Delivery across process restarts" below for
what `--resume` and `--final` mean.

## Input trace

One JSON object per line, in file order. Two message types:

- **event**: `{"type":"event","key":<string>,"ts":<int>,"val":<int>,"seq":<int>}`
- **watermark**: `{"type":"watermark","ts":<int>}`

Watermark timestamps are non-decreasing. The "current watermark" `W` starts
below every timestamp and becomes the largest watermark `ts` seen so far. After
fully processing each **event** message, print `ACK <seq>\n` to stdout (events
only, never watermarks) and flush.

## Session-window semantics (apply these rules exactly)

Maintain, per key, a set of sessions. A session is the closed interval
`[start, end]` spanning the timestamps of its member events, with running
aggregates `count` (number of events) and `sum` (total of `val`).

1. **Membership / merge.** An event with timestamp `ts` belongs to a session
   when `start - gap <= ts <= end + gap`. On an event for key `K`:
   - find every session of `K` the event is within gap of (open or finalized);
   - the event, plus all those sessions, merge into one session with
     `start = min`, `end = max`, `count` summed (+1 for the event), `sum` summed
     (+`val`). An event within gap of two sessions therefore **bridges** them.
   - If no session matches, the event starts a new session `[ts, ts]`.

2. **Finalize (window close).** When a watermark makes `W > end + gap` (strict
   greater-than) for a session, emit a `FINAL` record for it. The session stays
   **retractable** (not yet garbage-collected) after finalizing.

3. **Late events and retraction.** When an event arrives with
   `W - ts > lateness`, it is **too late**: drop it and increment the dropped
   count; never apply it. Otherwise apply it normally. If applying it merges one
   or more **finalized** (retractable) sessions, emit one `RETRACT` for each such
   finalized session, then merge; if the merged session still satisfies
   `W > end + gap` it is immediately re-finalized with one `FINAL`, otherwise it
   becomes open again.

4. **Garbage collection.** A finalized session stops being retractable once no
   allowed-late event could ever reach it: when `W > end + gap + lateness`
   (strict). Drop it from state at that point (no record is emitted for GC).

5. **End of trace.** After the last message, advance the watermark past every
   remaining session, emit a `FINAL` for each still-open session, then write the
   terminating `EOF` record (below).

## Output

Write one JSON object per line to `<out>`, each with **sorted keys**. Emission
records:

```
{"count":<int>,"emit":<int>,"end":<int>,"key":<str>,"start":<int>,"sum":<int>,"type":"FINAL"|"RETRACT"}
```

and a single terminating record:

```
{"dropped_late":<int>,"emit":<int>,"type":"EOF"}
```

`emit` is a 1-based counter that increases by exactly one per emitted record with
no gaps or duplicates across the whole run (including across resume). When a
single triggering message (a watermark, or a late event) produces several
records, append them in this **canonical order**: sort by `key`, then `start`,
then `end`, and for equal keys place `RETRACT` before `FINAL`; assign `emit` ids
in that order.

## Delivery across process restarts (exactly-once)

The stream is delivered across one or more process invocations. Each invocation
is handed a `<chunk>` file containing **only** the messages for that invocation —
a later invocation does **not** receive earlier messages and cannot re-read them.

- **First invocation** (no `--resume`): start a fresh `<out>`, process the chunk,
  and if `--final` is absent, write the full engine state to `<ckpt>`
  **atomically** (write a temp file, then rename over `<ckpt>`) and exit. Do
  **not** write the `EOF` record — the stream is not over.
- **Resume invocation** (`--resume`): reload the state from `<ckpt>`, **append**
  to the existing `<out>`, and process this chunk continuing seamlessly — the
  `emit` counter keeps climbing, open sessions and already-finalized (still
  retractable) sessions carry over, late events in this chunk may retract windows
  finalized in an earlier chunk. If `--final` is absent, persist state and exit.
- **Final invocation** (`--final`, with or without `--resume`): after processing
  the chunk, flush every remaining open window and write the single terminating
  `EOF` record.

Because a resume invocation only gets the unconsumed suffix, you cannot recompute
the pre-restart window state by reprocessing the stream — you must restore it from
the checkpoint you wrote. The concatenated `<out>` across all invocations must be
**byte-identical** to what a single invocation over the whole stream (with
`--final`) would produce: every record emitted exactly once, `emit` ids a gapless
`1..N`.

## Worked format example (a different, smaller configuration)

With `{"session_gap_ms":5,"allowed_lateness_ms":10,"checkpoint_interval":100}`
and the trace

```
{"type":"event","key":"x","ts":0,"val":3,"seq":0}
{"type":"event","key":"x","ts":2,"val":4,"seq":1}
{"type":"watermark","ts":20}
{"type":"event","key":"y","ts":18,"val":9,"seq":2}
```

stdout is `ACK 0`, `ACK 1`, `ACK 2`, and `<out>` is

```
{"count": 2, "emit": 1, "end": 2, "key": "x", "start": 0, "sum": 7, "type": "FINAL"}
{"count": 1, "emit": 2, "end": 18, "key": "y", "start": 18, "sum": 9, "type": "FINAL"}
{"dropped_late": 0, "emit": 3, "type": "EOF"}
```

(The two `x` events are within the gap, so they form one session `[0,2]` closed
by the watermark at 20; the `y` event forms its own session, finalized at end of
trace.) This only illustrates the line formats and the gap/close idea; the graded
configuration and traces differ.

## Constraints

One self-contained executable at `/app/stream`, Python standard library only, no
network, no subprocess. You have 3600 seconds. Do not use online solutions or
task-specific hints.
