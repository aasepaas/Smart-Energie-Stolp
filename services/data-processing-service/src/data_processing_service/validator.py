"""Validator (component 'Validator' in C4 3.3).

Controleert de geparste regels, in deze volgorde:
1. Negatieve waarden: geweigerd (de database staat ze niet toe, CHECK >= 0).
2. Dubbele regels (zelfde meter en UTC-kwartier):
   - exact gelijk: één keer houden, waarschuwing;
   - verschillende waarden: de regel met de nieuwste created_date/created_time houden
     (bij gelijke tijd de laatste in het bestand), waarschuwing met alle regelnummers.
3. Limieten per meter: boven de limiet wel opslaan, wel waarschuwen.
4. Gaps: ontbrekende kwartieren tussen het eerste en laatste kwartier van dezelfde meter.
   Er wordt niets ingevuld: een gap is een ontbrekende rij, nooit een nul.
   Een meter die later begint of eerder stopt dan de export krijgt een info-melding.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import DEFAULT_LIMITS_KWH, FALLBACK_LIMIT_KWH
from .models import Code, Gap, Issue, Severity

QUARTER = pd.Timedelta(minutes=15)


@dataclass
class ValidationResult:
    rows: pd.DataFrame      # regels die weggeschreven worden, één per (meter, ts)
    issues: list[Issue]
    gaps: list[Gap]
    rows_rejected: int
    rows_duplicate: int


def limit_for(meter_reference: str, meter_limits: dict[str, float] | None = None) -> float:
    """Limiet in kWh per kwartier: eerst per meter (settings), dan per type (KV/GV)."""
    if meter_limits and meter_reference in meter_limits:
        return meter_limits[meter_reference]
    return DEFAULT_LIMITS_KWH.get(meter_reference[:2], FALLBACK_LIMIT_KWH)


def validate(rows: pd.DataFrame, meter_limits: dict[str, float] | None = None) -> ValidationResult:
    issues: list[Issue] = []
    df = rows.copy()

    # 1. Negatieve waarden ------------------------------------------------------------
    negative = (df["to_grid_kwh"] < 0) | (df["from_grid_kwh"] < 0)
    for row in df[negative].itertuples():
        issues.append(_issue(row, Code.NEGATIVE_VALUE, Severity.ERROR,
                             f"negatieve waarde (to_grid {row.to_grid_kwh}, from_grid "
                             f"{row.from_grid_kwh}); niet opgeslagen, kwartier wordt een gap"))
    df = df[~negative]
    rows_rejected = int(negative.sum())

    # 2. Dubbelen -----------------------------------------------------------------------
    df = df.sort_values(["meter_reference", "ts", "created_at", "line"], na_position="first")
    key = ["meter_reference", "ts"]
    duplicated = df[df.duplicated(key, keep=False)]
    for (meter, ts), group in duplicated.groupby(key, sort=False):
        kept = group.iloc[-1]
        others = group.iloc[:-1]
        values = group[["to_grid_kwh", "from_grid_kwh"]].drop_duplicates()
        if len(values) == 1:
            for row in others.itertuples():
                issues.append(_issue(row, Code.DUPLICATE_EXACT, Severity.WARNING,
                                     f"regel is gelijk aan regel {int(kept.line)}; één keer opgeslagen"))
        else:
            lines = ", ".join(str(int(n)) for n in group["line"])
            issues.append(Issue(
                code=Code.DUPLICATE_CONFLICT, severity=Severity.WARNING,
                line=int(kept.line), meter_reference=meter, ts=ts.to_pydatetime(),
                message=(f"regels {lines} hebben verschillende waarden voor hetzelfde kwartier; "
                         f"regel {int(kept.line)} (nieuwste created) is opgeslagen")))
    rows_duplicate = int(df.duplicated(key).sum())
    df = df.drop_duplicates(key, keep="last")

    # 3. Limieten per meter ------------------------------------------------------------
    limits = df["meter_reference"].map(lambda m: limit_for(m, meter_limits))
    above = df[["to_grid_kwh", "from_grid_kwh"]].max(axis=1) > limits
    for row, limit in zip(df[above].itertuples(), limits[above]):
        issues.append(_issue(row, Code.ABOVE_LIMIT, Severity.WARNING,
                             f"waarde boven de limiet van {limit} kWh per kwartier (to_grid "
                             f"{row.to_grid_kwh}, from_grid {row.from_grid_kwh}); wel opgeslagen"))

    # 4. Gaps en gedeeltelijke periode ------------------------------------------------
    gaps: list[Gap] = []
    if not df.empty:
        period_start, period_end = df["ts"].min(), df["ts"].max()
        for meter, group in df.groupby("meter_reference"):
            ts = group["ts"].sort_values()
            step = ts.diff()
            for end, size in zip(ts[step > QUARTER], step[step > QUARTER]):
                quarters = int(size / QUARTER) - 1
                start = end - size + QUARTER
                gaps.append(Gap(meter, start.to_pydatetime(), end.to_pydatetime(), quarters))
                issues.append(Issue(code=Code.GAP, severity=Severity.WARNING,
                                    meter_reference=meter, ts=start.to_pydatetime(),
                                    message=f"{quarters} kwartier(en) ontbreken van "
                                            f"{start:%Y-%m-%d %H:%M} tot {end:%Y-%m-%d %H:%M} UTC"))
            first, last = ts.iloc[0], ts.iloc[-1]
            if first > period_start or last < period_end:
                issues.append(Issue(code=Code.PARTIAL_PERIOD, severity=Severity.INFO,
                                    meter_reference=meter, ts=first.to_pydatetime(),
                                    message=f"meter heeft data van {first:%Y-%m-%d %H:%M} t/m "
                                            f"{last:%Y-%m-%d %H:%M} UTC, de export van "
                                            f"{period_start:%Y-%m-%d %H:%M} t/m "
                                            f"{period_end:%Y-%m-%d %H:%M} UTC"))

    df = df.sort_values(["ts", "meter_reference"]).reset_index(drop=True)
    return ValidationResult(rows=df, issues=issues, gaps=gaps,
                            rows_rejected=rows_rejected, rows_duplicate=rows_duplicate)


def _issue(row, code: Code, severity: Severity, message: str) -> Issue:
    return Issue(code=code, severity=severity, message=message, line=int(row.line),
                 meter_reference=row.meter_reference, ts=row.ts.to_pydatetime())
