"""Simultaneity per quarter hour and pro rata distribution, with hand-calculated examples.

Each test builds a few readings as GET /readings returns them (kWh as text) and compares the
result with a calculation that can be checked by hand.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data_processing_service.simultaneity_calculator import (
    QuarterSimultaneity, Share, calculate, pro_rata, simultaneity_ratio)

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
D = Decimal


def q(n: int) -> datetime:
    """The n-th quarter after T0."""
    return T0 + timedelta(minutes=15 * n)


def reading(meter: str, n: int, to_grid: str = "0", from_grid: str = "0") -> dict:
    return {"meter_reference": meter, "ts": q(n).isoformat(),
            "to_grid_kwh": to_grid, "from_grid_kwh": from_grid}


# ---------- Rule: shared = min(total feed-in, total consumption) ----------

def test_shared_is_minimum_of_totals():
    # A feeds in 1.2, B and C consume 0.5 + 0.3 = 0.8 -> shared 0.8
    (row,) = calculate([reading("A", 0, to_grid="1.200"),
                        reading("B", 0, from_grid="0.500"),
                        reading("C", 0, from_grid="0.300")])
    assert row == QuarterSimultaneity(q(0), D("1.200"), D("0.800"), D("0.800"), 3)


def test_less_generation_than_consumption():
    (row,) = calculate([reading("A", 0, to_grid="0.250"), reading("B", 0, from_grid="1.000")])
    assert row.shared_kwh == D("0.250")


def test_no_netting_within_one_meter():
    # One meter feeds in and consumes in the same quarter: both count separately
    (row,) = calculate([reading("A", 0, to_grid="0.400", from_grid="0.100")])
    assert (row.total_to_grid_kwh, row.total_from_grid_kwh, row.shared_kwh) == \
        (D("0.400"), D("0.100"), D("0.100"))


def test_per_quarter_not_per_day():
    # Surplus at noon, only consumption in the morning, evening and night
    readings = [reading("A", 0, from_grid="3"),
                reading("A", 1, to_grid="10"), reading("B", 1, from_grid="2"),
                reading("B", 2, from_grid="6"),
                reading("B", 3, from_grid="2")]
    quarters = calculate(readings)
    assert [r.shared_kwh for r in quarters] == [D(0), D(2), D(0), D(0)]
    assert simultaneity_ratio(quarters) == D("0.2")  # not 1.0, which a daily total would give
    assert min(D(10), D(13)) / D(10) == 1  # what "per day" would look like


def test_sum_is_exact_with_three_decimals():
    # floats would give 0.1 + 0.2 = 0.30000000000000004; the CHECK in the database is exact
    (row,) = calculate([reading("A", 0, to_grid="0.100"), reading("B", 0, to_grid="0.200"),
                        reading("C", 0, from_grid="0.300")])
    assert row.total_to_grid_kwh == row.shared_kwh == D("0.300")
    assert row.to_payload() == {"ts": "2026-06-01T10:00:00+00:00", "total_to_grid_kwh": "0.300",
                                "total_from_grid_kwh": "0.300", "shared_kwh": "0.300",
                                "meter_count": 3}


def test_quarters_sorted_and_time_zones_aligned():
    # the same moment in another notation belongs to the same quarter
    summer_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))  # = T0
    readings = [reading("A", 1, to_grid="1"),
                {"meter_reference": "B", "ts": summer_time.isoformat(),
                 "to_grid_kwh": "0", "from_grid_kwh": "1"},
                reading("A", 0, to_grid="1")]
    rows = calculate(readings)
    assert [r.ts for r in rows] == [q(0), q(1)]
    assert rows[0].meter_count == 2 and rows[0].shared_kwh == D(1)


def test_decimal_and_float_input():
    (row,) = calculate([{"meter_reference": "A", "ts": q(0), "to_grid_kwh": 0.1,
                         "from_grid_kwh": D("0.050")}])
    assert row.total_to_grid_kwh == D("0.1") and row.shared_kwh == D("0.050")


def test_timestamp_without_time_zone_rejected():
    with pytest.raises(ValueError, match="time zone"):
        calculate([{"meter_reference": "A", "ts": "2026-06-01T10:00:00",
                    "to_grid_kwh": "0", "from_grid_kwh": "0"}])


# ---------- Edge cases ----------

def test_no_generation_gives_zero_shared():
    (row,) = calculate([reading("A", 0, from_grid="0.500"), reading("B", 0, from_grid="0.200")])
    assert row.shared_kwh == 0 and row.total_from_grid_kwh == D("0.700")


def test_no_consumption_gives_zero_shared():
    (row,) = calculate([reading("A", 0, to_grid="0.900")])
    assert row.shared_kwh == 0


def test_quarter_without_readings_gets_no_row():
    # quarter 1 is missing for all meters: no row with zeros, but a gap
    rows = calculate([reading("A", 0, to_grid="1"), reading("A", 2, to_grid="1")])
    assert [r.ts for r in rows] == [q(0), q(2)]


def test_missing_meter_does_not_count_as_zero():
    # B misses quarter 1: A still counts, meter_count shows the quarter is incomplete
    rows = calculate([reading("A", 0, to_grid="1"), reading("B", 0, from_grid="1"),
                      reading("A", 1, to_grid="1")])
    assert [(r.meter_count, r.shared_kwh) for r in rows] == [(2, D(1)), (1, D(0))]


def test_no_readings():
    assert calculate([]) == []
    assert simultaneity_ratio([]) is None


def test_ratio_without_generation_is_none():
    assert simultaneity_ratio(calculate([reading("A", 0, from_grid="1")])) is None


# ---------- Pro rata distribution over participants ----------

def test_pro_rata_by_consumption_and_feed_in():
    # A and B feed in 2 and 1 (3), C and D consume 1.5 and 0.5 (2) -> shared 2
    readings = [reading("A", 0, to_grid="2"), reading("B", 0, to_grid="1"),
                reading("C", 0, from_grid="1.5"), reading("D", 0, from_grid="0.5")]
    shares = pro_rata(readings)[q(0)]
    assert shares["C"].used_kwh == D("1.5")       # 1.5 / 2 * 2
    assert shares["D"].used_kwh == D("0.5")       # 0.5 / 2 * 2
    assert shares["A"].supplied_kwh == pytest.approx(D(4) / 3)  # 2 / 3 * 2
    assert shares["B"].supplied_kwh == pytest.approx(D(2) / 3)  # 1 / 3 * 2
    assert sum(s.used_kwh for s in shares.values()) == D(2)
    assert sum(s.supplied_kwh for s in shares.values()) == pytest.approx(D(2))


def test_pro_rata_per_participant_with_several_meters():
    readings = [reading("A", 0, to_grid="1"),
                reading("M1", 0, from_grid="0.2"), reading("M2", 0, from_grid="0.3"),
                reading("X", 0, from_grid="0.5")]  # X is not linked to anyone (yet)
    shares = pro_rata(readings, owner={"A": "p1", "M1": "p2", "M2": "p2", "X": None})[q(0)]
    assert shares == {"p1": Share(D(0), D(1)), "p2": Share(D("0.5"), D(0))}  # X does count


def test_pro_rata_without_generation_no_division_by_zero():
    shares = pro_rata([reading("A", 0, from_grid="1"), reading("B", 0)])[q(0)]
    assert shares == {"A": Share(D(0), D(0)), "B": Share(D(0), D(0))}


def test_pro_rata_per_quarter_separately():
    readings = [reading("A", 0, to_grid="1"), reading("B", 0, from_grid="1"),
                reading("B", 1, from_grid="1")]  # quarter 1: no generation
    shares = pro_rata(readings)
    assert shares[q(0)]["B"].used_kwh == 1 and shares[q(1)]["B"].used_kwh == 0
