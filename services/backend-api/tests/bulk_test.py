"""Bulktest: schrijft 9999 metingen via de Backend API, haalt ze terug en vergelijkt ze.

Werkt zoals de Data processing service: via HTTP met het service token,
niet rechtstreeks in de database. Na afloop worden de testmeter en de
testmetingen weer verwijderd (de database blijft bewaard in een volume,
ook als de dev-container stopt).

Uitvoeren in de terminal van de dev-container:

    python services/backend-api/scripts/bulk_check.py
    python services/backend-api/scripts/bulk_check.py --rows 50000   # ander aantal
    python services/backend-api/scripts/bulk_check.py --keep         # data laten staan

Gebruikt de omgevingsvariabelen BACKEND_API_URL, SES_TOKEN_PROCESSING en
DATABASE_URL (opruimen), die in de dev-container al klaarstaan.
"""

import argparse
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import psycopg

API_URL = os.environ.get("BACKEND_API_URL", "http://backend-api:8001/v1")
TOKEN = os.environ.get("SES_TOKEN_PROCESSING", "dev-processing")
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://ses:ses@db:5432/ses")
BATCH = 10_000  # gelijk aan MAX_BATCH in de API

# Ver in de toekomst, zodat de testdata nooit botst met echte metingen
START = datetime(2099, 1, 1, tzinfo=timezone.utc)


def kwh():
    """Willekeurige waarde met drie decimalen, zoals in de CSV."""
    return str(Decimal(random.randint(0, 5000)) / 1000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=9999)
    parser.add_argument("--keep", action="store_true", help="testdata niet opruimen")
    args = parser.parse_args()

    meter = f"BULK{uuid.uuid4().hex[:6].upper()}"
    end = START + timedelta(minutes=15 * args.rows)
    rows = [
        {
            "meter_reference": meter,
            "ts": (START + timedelta(minutes=15 * i)).isoformat(),
            "to_grid_kwh": kwh(),
            "from_grid_kwh": kwh(),
        }
        for i in range(args.rows)
    ]
    print(
        f"Testmeter {meter}: {args.rows} metingen van {START:%Y-%m-%d} tot {end:%Y-%m-%d %H:%M}"
    )

    api = httpx.Client(
        base_url=API_URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60
    )
    ok = False
    try:
        # 1. Meter aanmaken
        r = api.post("/meters", json={"meter_references": [meter]})
        r.raise_for_status()

        # 2. Metingen schrijven, in delen van maximaal BATCH rijen
        t0 = time.perf_counter()
        for i in range(0, len(rows), BATCH):
            r = api.put("/readings", json=rows[i : i + BATCH])
            r.raise_for_status()
        t_write = time.perf_counter() - t0
        print(f"Schrijven:  {args.rows} rijen in {t_write:.2f} s")

        # 3. Ophalen
        t0 = time.perf_counter()
        r = api.get(
            "/readings",
            params={
                "start": START.isoformat(),
                "end": end.isoformat(),
                "meter_reference": meter,
            },
        )
        r.raise_for_status()
        got = r.json()
        t_read = time.perf_counter() - t0
        print(f"Ophalen:    {len(got)} rijen in {t_read:.2f} s")

        # 4. Vergelijken: aantal, volgorde en elke waarde
        errors = []
        if len(got) != len(rows):
            errors.append(f"aantal: verstuurd {len(rows)}, terug {len(got)}")
        for sent, back in zip(rows, got):
            if datetime.fromisoformat(back["ts"]) != datetime.fromisoformat(sent["ts"]):
                errors.append(f"tijdstip: verwacht {sent['ts']}, kreeg {back['ts']}")
            for col in ("to_grid_kwh", "from_grid_kwh"):
                if Decimal(back[col]) != Decimal(sent[col]):
                    errors.append(
                        f"{col} op {sent['ts']}: verwacht {sent[col]}, kreeg {back[col]}"
                    )
            if len(errors) >= 10:
                break

        # 5. Opnieuw schrijven mag geen dubbele rijen opleveren (upsert)
        r = api.put("/readings", json=rows[:100])
        r.raise_for_status()
        r = api.get(
            "/readings",
            params={
                "start": START.isoformat(),
                "end": end.isoformat(),
                "meter_reference": meter,
            },
        )
        if len(r.json()) != len(rows):
            errors.append(
                f"na opnieuw schrijven: {len(r.json())} rijen in plaats van {len(rows)}"
            )

        if errors:
            print("\nMISLUKT:")
            for e in errors:
                print(f"  - {e}")
        else:
            print(
                "\nGESLAAGD: alle rijen zijn correct opgeslagen en opgehaald, zonder dubbelen."
            )
            ok = True

    except httpx.HTTPStatusError as e:
        print(
            f"\nMISLUKT: {e.request.method} {e.request.url.path} gaf {e.response.status_code}: {e.response.text}"
        )
    except httpx.ConnectError:
        print(
            f"\nMISLUKT: geen verbinding met {API_URL}. Draait de container backend-api?"
        )
    finally:
        api.close()
        if args.keep:
            print(f"Testdata blijft staan (meter {meter}).")
        else:
            # De API heeft geen endpoint om metingen te verwijderen; opruimen als superuser
            with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
                n = conn.execute(
                    "DELETE FROM readings WHERE meter_reference = %s", [meter]
                ).rowcount
                conn.execute("DELETE FROM meters WHERE meter_reference = %s", [meter])
            print(f"Opgeruimd: {n} testmetingen en meter {meter}.")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
