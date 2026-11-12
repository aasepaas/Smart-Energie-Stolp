"""Simultaneity calculator (component 'Simultaneity calculator' in C4 3.3).

Simultaneity of the whole Stolp per quarter hour, over all meters:

    total_to_grid   = sum of to_grid_kwh   of all meters in the quarter
    total_from_grid = sum of from_grid_kwh of all meters in the quarter
    shared          = min(total_to_grid, total_from_grid)

Why per quarter hour: min() is not additive. Calculating per day would let energy generated at
13:00 be used at 20:00, as if there were a battery, and gives a number that is too high. Day,
week and month are therefore only sums of quarters:

    KPI over a period = sum(shared) / sum(total_to_grid)

Rules:
- No netting per meter: to_grid and from_grid are summed separately.
- A quarter without readings gets no row (it stays a gap, it does not become 0). If one meter
  is missing, it does not count; meter_count shows how complete the quarter is.
- Calculate with Decimal: the input has 3 decimals, so the sums have too, and the CHECK
  shared = LEAST(...) on community_simultaneity always holds exactly.

The share of a participant is not stored but calculated on request (pro_rata).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


@dataclass(frozen=True)
class QuarterSimultaneity:
    """One row of community_simultaneity."""
    ts: datetime
    total_to_grid_kwh: Decimal
    total_from_grid_kwh: Decimal
    shared_kwh: Decimal
    meter_count: int

    def to_payload(self) -> dict[str, Any]:
        """Row for PUT /simultaneity. kWh as text with 3 decimals, like Decimal in the API."""
        return {"ts": self.ts.isoformat(),
                "total_to_grid_kwh": f"{self.total_to_grid_kwh:.3f}",
                "total_from_grid_kwh": f"{self.total_from_grid_kwh:.3f}",
                "shared_kwh": f"{self.shared_kwh:.3f}",
                "meter_count": self.meter_count}


@dataclass(frozen=True)
class Share:
    """Pro rata share of one participant (or meter) in the shared energy of a quarter."""
    used_kwh: Decimal      # part of the own consumption that came from local generation
    supplied_kwh: Decimal  # part of the own feed-in that was used locally


def calculate(readings: Iterable[Mapping[str, Any]]) -> list[QuarterSimultaneity]:
    """Readings (as returned by GET /readings) -> simultaneity per quarter, sorted by time.

    Each reading has meter_reference, ts (datetime or ISO text), to_grid_kwh and from_grid_kwh
    (Decimal, text or number).
    """
    to_grid: dict[datetime, Decimal] = defaultdict(lambda: ZERO)
    from_grid: dict[datetime, Decimal] = defaultdict(lambda: ZERO)
    meters: dict[datetime, set[str]] = defaultdict(set)

    for r in readings:
        ts = _timestamp(r["ts"])
        to_grid[ts] += _kwh(r["to_grid_kwh"])
        from_grid[ts] += _kwh(r["from_grid_kwh"])
        meters[ts].add(r["meter_reference"])

    return [QuarterSimultaneity(ts=ts, total_to_grid_kwh=to_grid[ts],
                                total_from_grid_kwh=from_grid[ts],
                                shared_kwh=min(to_grid[ts], from_grid[ts]),
                                meter_count=len(meters[ts]))
            for ts in sorted(meters)]


def pro_rata(readings: Iterable[Mapping[str, Any]],
             owner: Mapping[str, str | None] | None = None) -> dict[datetime, dict[str, Share]]:
    """Distribute the shared energy per quarter pro rata.

        used_kwh     = own from_grid / total_from_grid * shared
        supplied_kwh = own to_grid   / total_to_grid   * shared

    Without owner the energy is distributed per meter. With owner (meter_reference ->
    participant_id) shares are summed per participant; meters without a participant count in
    the totals but get no share. A total of 0 gives a share of 0. Not rounded: the sum of all
    shares equals shared; rounding is up to the presentation.
    """
    readings = list(readings)
    quarters = {q.ts: q for q in calculate(readings)}
    result: dict[datetime, dict[str, Share]] = defaultdict(dict)

    for r in readings:
        key = r["meter_reference"] if owner is None else owner.get(r["meter_reference"])
        if key is None:
            continue
        q = quarters[_timestamp(r["ts"])]
        used = _part(_kwh(r["from_grid_kwh"]), q.total_from_grid_kwh, q.shared_kwh)
        supplied = _part(_kwh(r["to_grid_kwh"]), q.total_to_grid_kwh, q.shared_kwh)
        previous = result[q.ts].get(key, Share(ZERO, ZERO))
        result[q.ts][key] = Share(previous.used_kwh + used, previous.supplied_kwh + supplied)

    return dict(result)


def simultaneity_ratio(quarters: Iterable[QuarterSimultaneity]) -> Decimal | None:
    """KPI over a period: sum(shared) / sum(total_to_grid). None if nothing was generated."""
    quarters = list(quarters)
    produced = sum((q.total_to_grid_kwh for q in quarters), ZERO)
    if produced == 0:
        return None
    return sum((q.shared_kwh for q in quarters), ZERO) / produced


def _part(own: Decimal, total: Decimal, shared: Decimal) -> Decimal:
    return own / total * shared if total else ZERO


def _kwh(value: Any) -> Decimal:
    # via str(): a float like 0.1 becomes Decimal("0.1"), not 0.1000000000000000055...
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _timestamp(value: datetime | str) -> datetime:
    ts = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError(f"timestamp without time zone: {value!r}")
    return ts
