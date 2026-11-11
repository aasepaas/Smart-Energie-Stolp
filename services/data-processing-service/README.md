# Data processing service

Container **Data processing service** (Python, FastAPI, pandas): importeert meterdata en berekent de gelijktijdigheid. Zie C4-view *3.3 - Component diagram for Data processing service*.

## Stappen per import

| Stap | Bestand | Status |
| --- | --- | --- |
| 1. CSV ontvangen (`POST /imports`), bestandsnaam en hash vastleggen | `import_endpoint.py` | klaar (US1.2) |
| 2. Stappen in volgorde uitvoeren, resultaat naar `import_log` | `import_orchestrator.py` | klaar (US1.2) |
| 3. Decimale komma en quotes, tijdstempel naar UTC | `csv_parser.py` | klaar (US1.2) |
| 4. Dubbelen, gaten (niet als 0) en grenzen per meter | `validator.py` | klaar (US1.2) |
| 5. Enige weg naar de Backend API | `backend_client.py` | voorbereid: alleen dry-run |
| 6. Meter-id naar deelnemer via de koppeltabel | `meter_linker.py` | later |
| 7. Gedeeld = min(teruglevering, afname) per kwartier | `simultaneity_calculator.py` | later |
| 8. Training pipeline starten | `training_notifier.py` | later |

De import is idempotent: exports mogen elkaar overlappen (upsert op meter + UTC-kwartier). Hetzelfde bestand (zelfde SHA-256) twee keer importeren geeft `duplicate` / `409`.

## Regels van de parser en validator (US1.2)

| Situatie | Wat gebeurt er | Ernst |
| --- | --- | --- |
| `"0,031"` (decimale komma, quotes) | wordt 0.031 | |
| Tijd | `interval_start` + `interval_time` (al in UTC, `+00`). `nl_date`/`nl_time` zijn alleen controle: bij wintertijd komt 02:00-03:00 lokaal twee keer voor | |
| `nl_date`/`nl_time` past niet bij de UTC-tijd | opgeslagen, UTC aangehouden | waarschuwing |
| Geen getal, leeg, ongeldige datum, geen tijdzone, niet op een kwartier, geen meter | regel geweigerd, kwartier wordt een gap | fout |
| Meer dan 3 decimalen | afgerond op 3 (database: `numeric(10,3)`) | waarschuwing |
| Onbekend metertype (geen KV, GV of `meter_` + 24 hex) | opgeslagen met de GV-limiet | waarschuwing |
| Negatieve waarde | geweigerd (database: `CHECK >= 0`), wordt een gap | fout |
| Dubbele regel, exact gelijk | één keer opgeslagen | waarschuwing |
| Dubbele regel, andere waarden | nieuwste `created_date`/`created_time` wint | waarschuwing |
| Boven de limiet (KV 13,8 / GV 43,3 kWh per kwartier) | wel opgeslagen | waarschuwing |
| Kwartier ontbreekt tussen eerste en laatste kwartier van een meter | gap gemeld, niets ingevuld (geen nul) | waarschuwing |
| Meter begint later of stopt eerder dan de export | gemeld, geen gap | info |
| Verplichte kolom ontbreekt, leeg bestand | hele import mislukt | fataal |

Limieten staan in `config.py` en kunnen later per meter uit de tabel `settings` komen (`limit_for(meter, meter_limits)`).

## Handmatig importeren

Installeren (in de dev-container):

```bash
pip install -e "services/data-processing-service[dev]"
```

Vanaf de command line:

```bash
cd services/data-processing-service
python -m data_processing_service tests/fixtures/testset_wintertijd_2026.csv      # importeren
python -m data_processing_service ../../data/meterdata.csv --validate-only        # alleen controleren
python -m data_processing_service ../../data/meterdata.csv --all                  # alle meldingen
python -m data_processing_service ../../data/meterdata.csv --json                 # rapport als JSON
```

Of via de API (Swagger op http://localhost:8000/docs):

```bash
uvicorn data_processing_service.import_endpoint:app --port 8000 --reload
curl -F "file=@tests/fixtures/testset_wintertijd_2026.csv" http://localhost:8000/imports
curl http://localhost:8000/imports/<import_id>
curl -F "file=@../../data/meterdata.csv" "http://localhost:8000/imports?validate_only=true"
```

## Koppeling met de Backend API (voorbereid)

De Backend API staat nog niet op main. `backend_client.py` heeft de interface `BackendClient` met dezelfde verzoeken als het contract op branch `ses-214-backend_api`: `GET/POST /v1/meters`, `PUT /v1/readings` (max. 10.000 rijen per verzoek), `POST /v1/imports` en `PATCH /v1/imports/{id}`.

Nu draait alles met de **dry-run backend** (`SES_BACKEND_MODE=dryrun`, standaard). Die schrijft elk verzoek als JSON in `data/dryrun/<import_id>/` (staat in `.gitignore`, want het is echte meterdata):

```
01_post_imports.json        02_post_meters.json        03_put_readings_0001.json ...
99_patch_imports.json       report.json
```

`data/dryrun/state.json` onthoudt bekende meters en hashes, zodat nieuwe meters en dubbele bestanden herkend worden. Andere map: `SES_DRYRUN_DIR=/pad`. Zodra de Backend API klaar is komt er een `HttpBackendClient` (httpx) bij met dezelfde methodes; de rest van de service verandert niet.

## Testdata en tests

`tests/fixtures/` bevat verzonnen CSV's met randgevallen (geen echte meterdata, dus wel in git). Opnieuw maken: `python tests/fixtures/genereer_fixtures.py`.

| Bestand | Randgeval |
| --- | --- |
| `geldig_klein.csv` | geldig, met BOM en quotes |
| `dst_maart.csv` / `dst_oktober.csv` | zomer- en wintertijd 2026 |
| `dubbelen.csv` | exacte en conflicterende dubbelen |
| `gaps.csv` | ontbrekende kwartieren en een later beginnende meter |
| `limieten.csv` | negatief en boven de limiet |
| `fouten.csv` | elke regel één fout of waarschuwing |
| `ontbrekende_kolom.csv` | fataal formaat |
| `testset_wintertijd_2026.csv` | complete testset voor handmatig importeren (3 meters, 2 dagen) |

```bash
cd services/data-processing-service
pytest -v
```
