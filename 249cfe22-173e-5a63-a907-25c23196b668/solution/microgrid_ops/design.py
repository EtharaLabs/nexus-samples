"""The reference policy's estimators and window planner (pure functions of what the API returned)."""

from __future__ import annotations

import math

from . import manual as M

HUNT_MIN_POINTS = 8
HUNT_A_MIN = 0.15  # Hz: a level with a fitted hunt amplitude below this counts as stable
FULL_LOG_POINTS = 120  # of the 180 ten-second samples in a 30-minute span; a level below this is censored


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least squares y = a0 + a1 x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    a1 = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - a1 * mx, a1


def fit_amplitude(points: list[list[float]]) -> float:
    """Amplitude of a sinusoid fitted to logged (hour, value) points, any period of 20 to 36 s."""
    if len(points) < HUNT_MIN_POINTS:
        return 0.0
    t = [p[0] * 3600.0 for p in points]
    y = [p[1] for p in points]
    best = None
    for k in range(0, 321):
        period = 20.0 + 0.05 * k
        w = 2.0 * math.pi / period
        s = [math.sin(w * x) for x in t]
        c = [math.cos(w * x) for x in t]
        n = len(t)
        # normal equations for y = m + a s + b c
        ss, cc, sc = sum(i * i for i in s), sum(i * i for i in c), sum(i * j for i, j in zip(s, c))
        s1, c1 = sum(s), sum(c)
        ys_, yc, y1 = sum(i * j for i, j in zip(s, y)), sum(i * j for i, j in zip(c, y)), sum(y)
        sol = _solve3([[n, s1, c1], [s1, ss, sc], [c1, sc, cc]], [y1, ys_, yc])
        if sol is None:
            continue
        m, a, b = sol
        sse = sum((yy - m - a * si - b * ci) ** 2 for yy, si, ci in zip(y, s, c))
        if best is None or sse < best[0]:
            best = (sse, math.hypot(a, b))
    return best[1] if best else 0.0


def _solve3(a: list[list[float]], b: list[float]):
    m = [row[:] + [rhs] for row, rhs in zip(a, b)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(m[r][i]))
        if abs(m[piv][i]) < 1e-12:
            return None
        m[i], m[piv] = m[piv], m[i]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [x - f * y for x, y in zip(m[r], m[i])]
    return [m[i][3] / m[i][i] for i in range(3)]


def pmin_from_rows(rows, naive: bool = False):
    """Minimum stable load from the censored recorder's logged points, one row per tested load.

    The recorder logs only excursions beyond the README.md deadband, so a level that barely hunts
    leaves no logged point. The censoring-aware estimate fits the hunt amplitude of the levels that
    clearly hunt against load and extrapolates it to zero; the naive reading takes the highest load
    at which any excursion was logged.
    """
    amps = [(sp, fit_amplitude(pts)) for sp, pts in rows]
    if naive:
        hunting = [sp for sp, pts in rows if len(pts) >= 3]
        return (max(hunting) if hunting else min(sp for sp, _ in rows)), amps
    # a level whose recorder logged nearly every 10-second sample is not censored; the others are
    # left out of the fit
    full = {sp: len(pts) for sp, pts in rows}
    use = [(sp, a) for sp, a in amps if full[sp] >= FULL_LOG_POINTS and a > HUNT_A_MIN]
    if len(use) < 2:
        return min(sp for sp, _ in rows), amps
    a0, a1 = linfit([sp for sp, _ in use], [a for _, a in use])
    return -a0 / a1, amps


def _tails(xs: list[float], frac: float = 0.05) -> float:
    s = sorted(xs)
    k = max(1, int(len(s) * frac))
    return sum(s[-k:]) / k - sum(s[:k]) / k


def knee_from_rows(rows) -> float:
    """Inverter derate knee from raw battery power at several commanded discharge powers."""
    pts = [(b, _tails(samples) / b) for b, samples in rows]
    use = [(b, s) for b, s in pts if 0.03 < s < 0.47]
    if len(use) >= 2:
        a0, a1 = linfit([b for b, _ in use], [s for _, s in use])
        return -a0 / a1
    if len(use) == 1:
        return use[0][0] - use[0][1]
    return max(b for b, _ in pts)


GROUPS = M.GROUPS


def _pm(tel, g: str, lo: float, hi: float) -> dict[float, float]:
    """A load meter's 15-minute means by interval start; values in kW (after a firmware unit
    change) are read back in MW."""
    out = {}
    for t, v in tel.series("PM-" + g, lo, hi):
        out[t] = v / 1000.0 if v > 50.0 else v
    return out


def _lsq(rows: list[list[float]], ys: list[float]) -> list[float]:
    n = len(rows[0])
    a = [[sum(r[i] * r[j] for r in rows) for j in range(n)] + [sum(r[i] * y for r, y in zip(rows, ys))]
         for i in range(n)]
    for i in range(n):
        piv = max(range(i, n), key=lambda k: abs(a[k][i]))
        a[i], a[piv] = a[piv], a[i]
        for k in range(n):
            if k != i:
                f = a[k][i] / a[i][i]
                a[k] = [x - f * y for x, y in zip(a[k], a[i])]
    return [a[i][n] / a[i][i] for i in range(n)]


def find_bias(tel, lo: float = 2.0, hi: float = 23.0):
    """The meter that reads off the plant energy balance: regress the balance residual on all
    load meters at once; the biased meter carries a coefficient near (f - 1) / f. (tag, coefficient)."""
    sup = {}
    for tag in ("PG-G1", "PG-G2", "PT-TIE", "PT-PV", "PT-BAT"):
        for t, v in tel.series(tag, lo, hi):
            sup[t] = sup.get(t, 0.0) + v
    dem = {g: _pm(tel, g, lo, hi) for g in GROUPS}
    ts = [t for t in sorted(sup) if all(t in dem[g] for g in GROUPS)]
    if len(ts) < 12:
        return None
    rows = [[dem[g][t] for g in GROUPS] for t in ts]
    ys = [sum(r) - sup[t] for r, t in zip(rows, ts)]
    beta = _lsq(rows, ys)
    k = max(range(len(GROUPS)), key=lambda i: abs(beta[i]))
    return ("PM-" + GROUPS[k], beta[k]) if abs(beta[k]) > 0.04 else None


def find_drift(tel, skip=(), lo: float = 24.0, hi: float = 45.0):
    """The meter whose reading departs from its own value 24 hours earlier: (tag, onset hour)."""
    best = None
    for g in GROUPS:
        if "PM-" + g in skip or g == "DOCK":
            continue
        cur = _pm(tel, g, lo, hi)
        prev = _pm(tel, g, lo - 24.0, hi - 24.0)
        pts = [(t, cur[t] / prev[t - 24.0] - 1.0) for t in sorted(cur) if (t - 24.0) in prev and prev[t - 24.0] > 0.05]
        if len(pts) < 20:
            continue
        dev = max(abs(x) for t, x in pts if t >= 36.0)
        if dev < 0.03:
            continue
        fit = None
        for k in range(0, 401):
            t0 = 20.0 + 0.05 * k
            h = [max(0.0, t - t0) for t, _ in pts]
            den = sum(a * a for a in h)
            if den <= 0:
                continue
            slope = sum(a * y for a, (_, y) in zip(h, pts)) / den
            sse = sum((y - slope * a) ** 2 for a, (_, y) in zip(h, pts))
            if fit is None or sse < fit[0]:
                fit = (sse, t0)
        if best is None or dev > best[0]:
            best = (dev, "PM-" + g, fit[1])
    return (best[1], best[2]) if best else None


CHARGE_MW = 2.4
SOC_TARGET = 0.97
RAMP_LOSS_H = 0.34


def block_cost(t0: float, t1: float, dr: list[tuple[float, float]]) -> float:
    """Import cost (EUR per MW) of charging over [t0, t1): Annex B tariff, or the penalty price in a
    demand-response event."""
    cost, t = 0.0, t0
    while t < t1 - 1e-9:
        nxt = min(t1, math.floor(t + 1e-9) + 1.0)
        in_dr = any(a <= t < b for a, b in dr)
        cost += (nxt - t) * (M.DR_PENALTY if in_dr else M.tariff(t))
        t = nxt
    return cost


def charge_blocks(now: float, t_open: float, need_dc: float, dr: list[tuple[float, float]]):
    """The cheapest import-charging blocks [(start, stop), ...] that end before the tie opens: the
    cheapest quarter hours, grouped into runs, each run losing one ramp's worth of energy."""
    t0 = math.ceil(now * 4.0) / 4.0
    slots = []
    t = t0
    while t + 0.25 <= t_open - 0.4 + 1e-9:
        slots.append((block_cost(t, t + 0.25, dr), t))
        t += 0.25
    hours = need_dc / (M.BAT_EFF * CHARGE_MW)
    for runs in (1, 2, 3):
        want = hours + RAMP_LOSS_H * runs
        chosen = sorted(sorted(slots, key=lambda s: (s[0], -s[1]))[: math.ceil(want * 4.0 - 1e-9)], key=lambda s: s[1])
        if len(chosen) * 0.25 < want - 1e-9:
            return None
        blocks: list[list[float]] = []
        for _, s in chosen:
            if blocks and abs(blocks[-1][1] - s) < 1e-9:
                blocks[-1][1] = s + 0.25
            else:
                blocks.append([s, s + 0.25])
        if len(blocks) <= runs:
            return [(a, b) for a, b in blocks]
    return [(a, b) for a, b in blocks]


def fuel_cost(out: float, flat: bool = False) -> float:
    if out <= 1e-9:
        return 0.0
    return out / (0.36 if flat else M.eta(out / M.G_RATED)) * M.FUEL_PRICE


def plan_window(prof: dict, shed_ok: list[str], e_dc: float, knee: float | None, pmin: float,
                bat_cost: float, n_gens: int | None = None, flat: bool = False, margin_p: float = 0.30,
                df_max: float = 0.40, inv: float = 2.4, low_gen: bool = False, max_bat: bool = False) -> dict | None:
    """The cheapest plan over one or two gensets in service (``n_gens`` fixes the number)."""
    plans = [_plan(prof, shed_ok, e_dc, knee, pmin, bat_cost, n, flat, margin_p, df_max, inv, low_gen, max_bat)
             for n in ((1, 2) if n_gens is None else (n_gens,))]
    plans = [p for p in plans if p]
    return min(plans, key=lambda p: (p["out_min"] if low_gen else (-p["bat"] if max_bat else 0.0), p["unit_cost"])) if plans else None


def _plan(prof, shed_ok, e_dc, knee, pmin, bat_cost, n_gens, flat, margin_p, df_max, inv, low_gen=False,
          max_bat=False):
    """Hold-through plan for hours 66 to 72: genset set point, battery discharge, shed groups.

    ``prof`` maps a group to its six hourly demands (MW). Loads are read hour by hour; the genset
    droop (datasheet) carries the difference between load, battery output, and set points."""
    kk = n_gens * M.G_RATED / (M.DROOP * 50.0)
    bmax = inv if knee is None else max(0.0, knee - 0.06)
    best = None
    subsets = [[g for i, g in enumerate(shed_ok) if m >> i & 1] for m in range(1 << len(shed_ok))]
    for shed in subsets:
        load = [sum(v[k] for g, v in prof.items() if g not in shed) for k in range(6)]
        served = sum(load)
        for step in range(0, 121):
            b = 0.02 * step
            if b > bmax + 1e-9 or sum(b / M.BAT_EFF for _ in range(6)) > e_dc:
                break
            gen = [l_ - b for l_ in load]
            lo, hi = min(gen), max(gen)
            per_lo, per_hi = lo / n_gens, hi / n_gens
            if per_lo < pmin + margin_p or per_hi > 2.85 or (hi - lo) / (2 * kk) > df_max:
                continue
            cost = sum(fuel_cost(g_ / n_gens, flat) * n_gens for g_ in gen) + bat_cost * 6 * b / M.BAT_EFF
            unit = cost / served
            key = (round(lo / n_gens, 3) if low_gen else (-round(b, 3) if max_bat else 0.0), round(unit, 3), len(shed))
            if best is None or key < best[0]:
                best = (key, {"shed": shed, "bat": round(b, 3), "sp_total": round((hi + lo) / 2, 3),
                              "unit_cost": round(unit, 2), "out_min": round(lo / n_gens, 3), "n": n_gens})
    return None if best is None else best[1]
