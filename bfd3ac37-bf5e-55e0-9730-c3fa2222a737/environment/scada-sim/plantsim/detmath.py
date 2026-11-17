"""Platform-independent transcendental functions.

The simulator must produce bit-identical trajectories on linux/amd64 and linux/arm64. The C
library's exp, log, sin, and pow are not guaranteed to round identically on both, so every
transcendental the simulator needs is computed here from IEEE-754 addition, multiplication,
division, and the exactly rounded ``math.sqrt``, ``math.frexp``, and ``math.ldexp``.
"""

from __future__ import annotations

import math

_LN2 = 0.6931471805599453
_TWO_PI = 6.283185307179586


def exp(x: float) -> float:
    if x > 700.0:
        x = 700.0
    if x < -700.0:
        return 0.0
    k = math.floor(x / _LN2 + 0.5)
    r = x - k * _LN2
    term = 1.0
    total = 1.0
    for n in range(1, 18):
        term = term * r / n
        total += term
    return math.ldexp(total, int(k))


def log(x: float) -> float:
    if x <= 0.0:
        raise ValueError("log of a non-positive number")
    m, e = math.frexp(x)  # x = m * 2**e, 0.5 <= m < 1
    if m < 0.7071067811865476:
        m *= 2.0
        e -= 1
    s = (m - 1.0) / (m + 1.0)
    s2 = s * s
    term = s
    total = 0.0
    for n in range(1, 40, 2):
        total += term / n
        term *= s2
    return 2.0 * total + e * _LN2


def pow_(base: float, exponent: float) -> float:
    if base <= 0.0:
        return 0.0
    return exp(exponent * log(base))


def sin(x: float) -> float:
    k = math.floor(x / _TWO_PI)
    r = x - k * _TWO_PI  # 0 <= r < 2*pi
    sign = 1.0
    if r > math.pi:
        r -= math.pi
        sign = -1.0
    if r > math.pi / 2.0:
        r = math.pi - r
    r2 = r * r
    term = r
    total = r
    for n in range(1, 12):
        term = -term * r2 / ((2 * n) * (2 * n + 1))
        total += term
    return sign * total
