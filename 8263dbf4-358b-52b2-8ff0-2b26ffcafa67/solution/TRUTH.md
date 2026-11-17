# GENERATED SECTION. DO NOT HAND-EDIT.

# Golden trajectory: dhawal-bathre/stream-session-window-exactly-once

The shipped /app/stream only ACKs events and writes an EOF record. The fix
implements per-key gap session windows, watermark finalization, late-event
retraction and re-finalization, the dropped-late count, atomic checkpointing,
and exactly-once resume across chunked process restarts (suffix-only resume;
state restored from the checkpoint). The verifier compares the agent's output against
the embedded reference, clean and across crash/resume, over seeded traces and
two field configs.

## Compiled criteria

- C1 (outcome, w5): on the primary seeded trace the clean-run output file is byte-identical to the reference output (no-crash correctness)
- C2 (robustness, w5): the output file is byte-identical to the reference after the stream is split into two chunks at a seed-chosen boundary and run as first-chunk then --resume --final (exactly-once across one restart)
- C3 (outcome, w3): the dropped_late count in the terminating EOF record matches the reference on the primary trace
- C4 (robustness, w3): after resume no checkpoint .tmp file is left behind and every output line parses as JSON (atomic checkpoint, no partial write)
- C5 (outcome, w3): under the second field config the clean-run output is byte-identical to the reference
- C6 (coverage, w3): the set and order of RETRACT records match the reference on a retraction-heavy seed
- C7 (outcome, w3): the set and order of FINAL records match the reference on the primary seed
- C8 (robustness, w3): the stream split into three chunks (two restarts at different boundaries) still produces byte-identical output
- C9 (coverage, w3): per-key session boundaries (merge across the gap) match the reference on a bridge-engineered seed
- C10 (robustness, w3): under the second field config the crash-and-resume output is byte-identical to the reference
- C11 (craft, w1): every output line is a JSON object with sorted keys and exactly the documented fields
- C12 (constraints, w1): the emit ids are 1-based, strictly increasing by one, with no gaps or duplicates across the whole output
- C13 (robustness, w1): two clean runs of the same trace produce identical output (determinism)
- C14 (constraints, w1): a crash before the first checkpoint commits still resumes to a byte-identical output
- C15 (craft, w1): the output ends with exactly one EOF record carrying dropped_late and nothing follows it

## Judged criteria

- J1 (process, w5): Logical time advances only through watermark messages from the input, or the single documented end-of-trace advance that flushes remaining open windows before the EOF record (instruction Section 5); no wall-clock, system-time, or random source influences windowing, finalization, or the crash point. A program that implements no windowing or finalization logic does not satisfy this.
- J2 (process, w3): A session groups events for one key whose timestamps lie within the configured gap, and its window is the minimum and maximum timestamp of its member events.
- J3 (process, w3): A window is finalized when the watermark passes end plus gap using the strict greater-than direction specified.
- J4 (process, w3): A late event within allowed lateness that falls within gap of one or more finalized sessions retracts each of them and merges; the merged session is then immediately re-finalized with one FINAL if it still satisfies watermark greater than end plus gap, or otherwise reopened with no re-FINAL, per instruction Section 3. The RETRACT records must always be emitted and both the re-FINAL and reopen branches are correct.
- J5 (process, w3): An event whose watermark-minus-timestamp exceeds allowed lateness is dropped and counted, never applied to any window.
- J6 (constraints, w3): The checkpoint records the emit counter so a resumed invocation continues the gapless 1..N numbering instead of restarting it.
- J7 (process, w3): Records emitted for a single triggering message are ordered by the tuple (key, start, end), with RETRACT before FINAL only as the tie-break for records sharing an identical (key, start, end); start and end take priority over record type, not processing or insertion order.
- J8 (robustness, w3): Checkpoints are written atomically by writing a temporary file and renaming it, so a crash never leaves a partially written checkpoint.
- J9 (outcome, w3): The count and sum reported for a session are the exact totals of its member events after every merge.
- J10 (robustness, w1): The program makes no network call and spawns no subprocess, and it actually implements the documented session-window engine; a stub or no-op that merely avoids forbidden calls by doing nothing does not satisfy this.
- J11 (robustness, w1): No per-trace output, session boundary, or dropped count is hard-coded in the program.
- J12 (craft, w1): The deliverable is one self-contained executable using only the Python standard library that implements the documented session-window, finalization, retraction, and checkpoint/resume behavior, not a stub.
- J13 (constraints, w1): A finalized session is garbage-collected only once no allowed-late event can still reach it, when the watermark passes end plus gap plus allowed lateness.
- J14 (craft, w1): The output is JSON Lines with sorted keys and a single terminating EOF record carrying the dropped-late count.

Reward-gating (binary cut): reward = 1.0 only if all seventeen compiled criteria (C1-C17) pass (`[scoring.test_output] aggregation = "all-pass"`); C1 and C2 (byte-exact clean and crash/resume output) fail any miscorrecting or non-exactly-once engine. J1-J14 are scored and recorded for review but carry weight 0 and do not gate.

Caveat: reference_alt.py independently re-derives the window/merge/finalize/
lateness/GC/resume mechanics, but intentionally shares reference.py's canonical
emission order (sort by (key, start, end), then RETRACT-before-FINAL only on an
identical (key, start, end) tie); the cross-check does not independently
validate that ordering choice.
