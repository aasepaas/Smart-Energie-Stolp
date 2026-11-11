"""Genereert de synthetische test-CSV's met randgevallen (SCRUM-16).

Alle meters en waarden zijn verzonnen; dit is geen echte meterdata en mag dus wel in git.
Het formaat is gelijk aan de export van de netbeheerder:

    meter_reference,interval_start,interval_time,nl_weekday,nl_date,nl_time,
    to_grid_kWh,from_grid_kWh,created_date,created_time

Opnieuw genereren (vanuit deze map):  python genereer_fixtures.py
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HIER = Path(__file__).parent
NL = ZoneInfo("Europe/Amsterdam")
KWARTIER = timedelta(minutes=15)
HEADER = [
    "meter_reference", "interval_start", "interval_time", "nl_weekday", "nl_date",
    "nl_time", "to_grid_kWh", "from_grid_kWh", "created_date", "created_time",
]
STANDAARD_CREATED = datetime(2026, 11, 1, 6, 30, 45, tzinfo=timezone.utc)


def utc(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst).replace(tzinfo=timezone.utc)


def kwh(waarde: float) -> str:
    """Zoals de netbeheerder: decimale komma, minimaal 1 decimaal."""
    tekst = f"{waarde:.3f}".rstrip("0")
    if tekst.endswith("."):
        tekst += "0"
    return tekst.replace(".", ",")


def rij(meter: str, ts: datetime, to_grid: float, from_grid: float,
        created: datetime = STANDAARD_CREATED, **ruw: str) -> list[str]:
    """Eén CSV-regel. Met **ruw kun je een veld letterlijk overschrijven (foute invoer)."""
    lokaal = ts.astimezone(NL)
    velden = {
        "meter_reference": meter,
        "interval_start": ts.strftime("%Y-%m-%d"),
        "interval_time": ts.strftime("%H:%M:%S") + "+00",
        "nl_weekday": str(lokaal.isoweekday()),
        "nl_date": lokaal.strftime("%Y-%m-%d"),
        "nl_time": lokaal.strftime("%H:%M:%S"),
        "to_grid_kWh": kwh(to_grid),
        "from_grid_kWh": kwh(from_grid),
        "created_date": created.strftime("%Y-%m-%d"),
        "created_time": created.strftime("%H:%M:%S") + "+00",
    }
    velden.update(ruw)
    return [velden[k] for k in HEADER]


def reeks(meter: str, start: datetime, aantal: int, basis: float = 0.05) -> list[list[str]]:
    """Aaneengesloten kwartieren met een simpel, herkenbaar verbruikspatroon."""
    rijen = []
    for i in range(aantal):
        ts = start + i * KWARTIER
        rijen.append(rij(meter, ts, 0.0, round(basis + (i % 4) * 0.01, 3)))
    return rijen


def schrijf(naam: str, rijen: list[list[str]], header: list[str] = HEADER,
            bom: bool = False) -> None:
    pad = HIER / naam
    with pad.open("w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rijen)
    print(f"{naam}: {len(rijen)} regels")


def main() -> None:
    # 1. Geldig, klein, met BOM: twee meters, 8 kwartieren, alles goed.
    start = utc("2026-06-01 10:00:00")
    rijen = reeks("KV90", start, 8) + reeks("GV90", start, 8, basis=1.2)
    rijen[3] = rij("KV90", start + 3 * KWARTIER, 0.476, 0.0)  # teruglevering
    schrijf("geldig_klein.csv", rijen, bom=True)

    # 2. Zomertijd: zondag 29 maart 2026 gaat de klok om 02:00 lokaal naar 03:00.
    #    In UTC loopt alles gewoon door; nl_time springt van 01:45 naar 03:00.
    schrijf("dst_maart.csv", reeks("KV90", utc("2026-03-29 00:00:00"), 8))

    # 3. Wintertijd: zondag 25 oktober 2026 komt 02:00-03:00 lokaal twee keer voor.
    #    nl_date + nl_time is dan dubbel, interval_start + interval_time niet.
    schrijf("dst_oktober.csv", reeks("KV90", utc("2026-10-24 23:30:00"), 10))

    # 4. Dubbelen: exact gelijk (KV90 10:15) en conflicterend (KV90 10:30, nieuwste wint).
    start = utc("2026-06-01 10:00:00")
    rijen = reeks("KV90", start, 4)
    rijen.append(rijen[1])  # exacte kopie van 10:15
    rijen.append(rij("KV90", start + 2 * KWARTIER, 0.0, 0.999,
                     created=STANDAARD_CREATED + timedelta(days=1)))  # nieuwere correctie
    schrijf("dubbelen.csv", rijen)

    # 5. Gaps: KV90 mist 10:30 en 10:45 (2 kwartieren), KV91 begint pas om 11:00.
    rijen = reeks("KV90", start, 8)
    del rijen[2:4]
    rijen += reeks("KV91", start + 4 * KWARTIER, 4)
    schrijf("gaps.csv", rijen)

    # 6. Limieten: negatieve waarde (weigeren) en boven de limiet (opslaan + waarschuwen).
    rijen = reeks("KV90", start, 4) + reeks("GV90", start, 4, basis=1.0)
    rijen[1] = rij("KV90", start + KWARTIER, 0.0, 20.0)       # KV-limiet is 13,8
    rijen[2] = rij("KV90", start + 2 * KWARTIER, 0.0, 0.1, from_grid_kWh="-0,250")
    rijen[6] = rij("GV90", start + 2 * KWARTIER, 50.0, 0.0)   # GV-limiet is 43,3
    schrijf("limieten.csv", rijen)

    # 7. Foute regels: elke regel heeft één probleem; de geldige regels moeten blijven.
    rijen = reeks("KV90", start, 2)
    t = start + 2 * KWARTIER
    rijen += [
        rij("KV90", t, 0, 0, to_grid_kWh="abc"),                       # geen getal
        rij("KV90", t + KWARTIER, 0, 0, from_grid_kWh=""),             # leeg
        rij("KV90", t, 0, 0.1, interval_time="10:37:00+00"),           # geen kwartier
        rij("KV90", t, 0, 0.1, interval_time="10:30:00"),              # geen tijdzone
        rij("KV90", t, 0, 0.1, interval_start="2026-13-01"),           # ongeldige datum
        rij("", t, 0, 0.1),                                            # geen meter
        rij("KV90", t + 2 * KWARTIER, 0, 0, from_grid_kWh="0,12345"),  # te veel decimalen
        rij("KV90", t + 3 * KWARTIER, 0, 0.1, nl_time="23:00:00"),     # nl_time klopt niet
        rij("XYZ1", t, 0, 0.1),                                        # onbekend metertype
        rij("meter_0123456789abcdef01234567", t, 0, 0.1),              # pseudoniem (geldig)
    ]
    schrijf("fouten.csv", rijen)

    # 8. Ontbrekende kolom: zonder from_grid_kWh kan de import niet.
    kolommen = [k for k in HEADER if k != "from_grid_kWh"]
    rijen = [[w for k, w in zip(HEADER, r) if k != "from_grid_kWh"] for r in reeks("KV90", start, 2)]
    schrijf("ontbrekende_kolom.csv", rijen, header=kolommen)

    # 9. Testset voor handmatig importeren: 3 meters, 2 dagen rond de wintertijd,
    #    met een dubbele, een gap, een limietoverschrijding en een foute regel.
    start = utc("2026-10-24 00:00:00")
    rijen = (reeks("KV90", start, 192) + reeks("KV91", start, 192, basis=0.03)
             + reeks("GV90", start + 96 * KWARTIER, 96, basis=2.0))
    rijen[10] = rij("KV90", start + 10 * KWARTIER, 0.0, 15.5)          # boven KV-limiet
    del rijen[250:254]                                                 # gap van 4 kwartieren in KV91
    rijen.append(rijen[20])                                            # exacte dubbele
    rijen.append(rij("KV91", start + 5 * KWARTIER, 0, 0, to_grid_kWh="n/a"))  # foute regel
    schrijf("testset_wintertijd_2026.csv", rijen)


if __name__ == "__main__":
    main()
