"""The family clock: 72 plant hours, graded window 66 to 72, 300 wall seconds per plant hour.

The simulation step is a member choice (``step_s`` divides 60); every count below is in steps.
"""

from __future__ import annotations

HOURS = 72
WINDOW_START_HOUR = 66
WALL_S_PER_HOUR = 300.0
RAMP_S = 1200  # a change ramps over 20 plant minutes
MAX_CHANGES = 40
INTERVAL_S = 900  # telemetry averages over 15 plant minutes
RAW_SPAN_S = 1800  # one raw-sample request covers 30 plant minutes
RAW_QUOTA = 40


class Clock:
    def __init__(self, step_s: int):
        if step_s <= 0 or 60 % step_s:
            raise ValueError("step_s must divide 60")
        self.step_s = step_s
        self.steps_per_hour = 3600 // step_s
        self.n_steps = HOURS * self.steps_per_hour
        self.window_start = WINDOW_START_HOUR * self.steps_per_hour
        self.ramp_steps = RAMP_S // step_s
        self.interval = INTERVAL_S // step_s
        self.raw_span = RAW_SPAN_S // step_s
        self.wall_s_per_step = WALL_S_PER_HOUR / self.steps_per_hour
        self.dt_h = step_s / 3600.0

    def hour(self, step: int) -> float:
        return step / self.steps_per_hour

    def step_at(self, hour: float) -> int:
        return int(round(hour * self.steps_per_hour))
