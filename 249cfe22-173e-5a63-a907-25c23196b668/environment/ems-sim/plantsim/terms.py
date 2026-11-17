"""The contract terms as documents state them: tariff, prices, demand shapes, contracted energy,
and the revision schedule each seed carries. Pure functions of an hour or a parameter dictionary.
"""

from __future__ import annotations

from .params import CRIT0, GROUPS, PEAK

FUEL_PRICE = 60.0  # EUR per MWh of fuel (net calorific value), Annex B
DR_PENALTY = 480.0  # EUR per MWh imported during a demand-response event, Annex B
COST_CAP = 139.0  # EUR per MWh served, CONTRACT.md rule O3
BAT_COST0 = 95.0  # EUR per MWh stored cost at the start of the run
CONTRACT_FRACTION = 0.99  # Annex A: contracted critical power as a fraction of the nominal profile
EARLY_DR = (11, 14)  # the first Annex C event (hours 11 to 14), the decoy seen before hour 60


def _shape(group: str, c: float) -> float:
    """Nominal demand shape of a group at clock hour ``c`` (0 to 24)."""
    if group == "HOSP":
        return 0.92 + 0.08 * (1.0 if 8 <= c < 20 else 0.0)
    if group == "WATER":
        return 0.80 if c < 5 or c >= 22 else (1.0 if 6 <= c < 10 or 17 <= c < 21 else 0.88)
    if group == "TELCO":
        return 0.95
    if group == "MILL":
        return 0.35 if c < 6 else (0.5 if c >= 22 else (1.0 if 7 <= c < 17 else 0.68))
    if group == "TOWN":
        if c < 5:
            return 0.42
        if c < 7:
            return 0.65
        if c < 17:
            return 0.6
        return 1.0 if c < 22 else 0.85
    if group == "DOCK":
        return 0.25 if c < 6 else (0.45 if c >= 22 else (0.9 if 8 <= c < 20 else 0.55))
    raise KeyError(group)


def nominal_mw(group: str, hour: float) -> float:
    """Nominal demand (MW) of a group; the Annex A table lists it by hour."""
    return PEAK[group] * _shape(group, hour % 24.0)


def tariff(hour: float) -> float:
    """Annex B import tariff, EUR per MWh, by plant hour."""
    h = int(hour)
    if 46 <= h < 62:
        return 58.0
    c = h % 24
    if c < 6:
        return 110.0
    if c < 10:
        return 125.0
    if c < 16:
        return 105.0
    if c < 22:
        return 210.0
    return 125.0


def contracted_mw(group: str, hour: float) -> float:
    return round(CONTRACT_FRACTION * nominal_mw(group, hour), 3)


def tie_open_hour(p: dict, hour: float) -> float:
    """The tie-open hour as CONTRACT.md Annex C states it at plant ``hour`` (after revisions)."""
    return p["h_out1"] if hour >= p["rv_out_issue"] else p["h_out0"]


def dr_events(p: dict) -> list[tuple[float, float, str]]:
    """Annex C events as finally in force: (start, end, group)."""
    g = p["dr_group"]
    return [
        (float(EARLY_DR[0]), float(EARLY_DR[1]), g),
        (p["dr_start"], p["dr_start"] + p["dr_len"] + p["dr_ext"], g),
    ]


def dr_active(p: dict, hour: float) -> str | None:
    for a, b, g in dr_events(p):
        if a <= hour < b:
            return g
    return None


def crit_list(p: dict, hour: float) -> tuple[str, ...]:
    """The critical load groups in force at ``hour`` for grading (RV-CRIT effective hour)."""
    if hour < p["rv_crit_eff"]:
        return CRIT0
    return tuple(g for g in GROUPS if (g in CRIT0 and g != p["crit_out"]) or g == p["crit_in"])


def messages(p: dict) -> list[dict]:
    """The utility operator's three revisions, each listed only from its issued hour."""
    dr0 = p["dr_start"] + p["dr_len"]
    new_list = [g for g in GROUPS if (g in CRIT0 and g != p["crit_out"]) or g == p["crit_in"]]
    return [
        {
            "id": "RV-OUT", "issued_hour": p["rv_out_issue"], "effective_hour": p["h_out1"],
            "type": "outage-earlier",
            "terms": {"annex": "C", "tie_open_hour": p["h_out1"]},
        },
        {
            "id": "RV-DR", "issued_hour": p["rv_dr_issue"], "effective_hour": p["dr_start"],
            "type": "dr-extended",
            "terms": {"annex": "C", "event_group": p["dr_group"], "event_start_hour": p["dr_start"],
                      "event_end_hour": dr0 + p["dr_ext"]},
        },
        {
            "id": "RV-CRIT", "issued_hour": p["rv_crit_issue"], "effective_hour": p["rv_crit_eff"],
            "type": "critical-list-revised",
            "terms": {"annex": "A", "critical_before_effective": list(CRIT0),
                      "critical_from_effective": new_list,
                      "contracted_mw": {g: [contracted_mw(g, h) for h in range(66, 72)] for g in GROUPS}},
        },
    ]


def segments(p: dict) -> list[tuple[float, float, tuple[str, ...]]]:
    e = p["rv_crit_eff"]
    return [(66.0, e, crit_list(p, 66.0)), (e, 72.0, crit_list(p, e))]


def contracted_mwh(p: dict, a: float, b: float, groups) -> float:
    """Contracted critical energy of ``groups`` over [a, b) hours, from the hourly Annex A table."""
    total = 0.0
    h = a
    while h < b - 1e-9:
        total += sum(contracted_mw(g, int(h)) for g in groups) * min(1.0, b - h)
        h = int(h) + 1
    return total
