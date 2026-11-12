"""Checks the invented meter data in database/seed.

- The Data processing service accepts every row and reports only the built-in situations.
- The data behaves like a real community: feed-in and consumption in the same quarter,
  simultaneity per quarter well below the misleading daily figure.

The last two groups need the data_processing_service package (installed in the dev container).
"""

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

SEED = Path(__file__).parent
DATA = SEED / "meter_data_4_weeks.csv"
PARTICIPANTS = SEED / "participants.csv"


def test_participants_and_meters():
    with open(PARTICIPANTS, newline="") as f:
        links = list(csv.DictReader(f))
    assert len({r["participant"] for r in links}) == 20
    assert len({r["meter_reference"] for r in links}) == 21
    assert [r["meter_reference"] for r in links if r["participant"] == "P07"] == ["KV07", "KV21"]


@pytest.fixture(scope="module")
def validated():
    pytest.importorskip("data_processing_service")
    from data_processing_service.csv_parser import parse_csv
    from data_processing_service.validator import validate

    parsed = parse_csv(DATA.read_bytes())
    return parsed, validate(parsed.rows)


def test_every_row_accepted(validated):
    parsed, result = validated
    assert parsed.rows_rejected == result.rows_rejected == result.rows_duplicate == 0
    assert parsed.rows_in_file == len(result.rows) == 52328
    assert not [i for i in parsed.issues if i.code.value == "local_time_mismatch"]  # DST is right
    assert result.rows["meter_reference"].nunique() == 21
    assert result.rows["ts"].nunique() == 28 * 96 - 4  # 4 weeks, one hour less on 29 March


def test_only_built_in_situations_reported(validated):
    _, result = validated
    (gap,) = result.gaps
    assert (gap.meter_reference, gap.quarters) == ("KV04", 12)  # outage of 3 hours
    partial = {i.meter_reference for i in result.issues if i.code.value == "partial_period"}
    assert partial == {"KV07", "KV21", "KV18"}  # meter switch and a participant joining later
    assert {i.code.value for i in result.issues} == {"gap", "partial_period"}


def test_behaves_like_a_community(validated):
    from data_processing_service.simultaneity_calculator import calculate, simultaneity_ratio

    rows = validated[1].rows
    assert ((rows["to_grid_kwh"] > 0) & (rows["from_grid_kwh"] > 0)).sum() > 1000  # no netting
    quarters = calculate({"meter_reference": r.meter_reference, "ts": r.ts.to_pydatetime(),
                          "to_grid_kwh": Decimal(f"{r.to_grid_kwh:.3f}"),
                          "from_grid_kwh": Decimal(f"{r.from_grid_kwh:.3f}")}
                         for r in rows.itertuples())
    ratio = simultaneity_ratio(quarters)
    assert Decimal("0.2") < ratio < Decimal("0.5")

    # per day the same data would look almost perfect: the reason to calculate per quarter
    days = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for q in quarters:
        days[q.ts.date()][0] += q.total_to_grid_kwh
        days[q.ts.date()][1] += q.total_from_grid_kwh
    per_day = sum(min(to, fr) for to, fr in days.values()) / sum(to for to, _ in days.values())
    assert per_day > Decimal("0.9") > ratio
