# Data processing service

Container **Data processing service** (Python, FastAPI, pandas): importeert meterdata en berekent de gelijktijdigheid. Zie C4-view *3.3*.

## Opbouw

```
src/data_processing_service/
  import_endpoint.py      POST /imports, GET /imports/{id}
  import_orchestrator.py  voert de stappen in volgorde uit
  csv_parser.py           decimale komma, quotes, tijd naar UTC
  validator.py            dubbelen, gaps, limieten per meter
  simultaneity_calculator.py  simultaneity per quarter hour, pro rata share, KPI
  backend_client.py       enige weg naar de Backend API (httpx)
  models.py               importrapport en meldingen
  config.py               limieten en instellingen
  __main__.py             handmatig importeren vanaf de command line
tests/
  test_*.py               unit tests
  fixtures/*.csv          verzonnen testdata met randgevallen
```

`meter_linker.py` and `training_notifier.py` follow later.

## Regels bij het inlezen

- Tijd komt uit `interval_start` + `interval_time` (al UTC). `nl_date`/`nl_time` zijn alleen controle, want bij wintertijd komt 02:00-03:00 lokaal twee keer voor.
- Foute regel (geen getal, leeg, ongeldige tijd, negatief): geweigerd, het kwartier wordt een gap.
- Ontbrekend kwartier: gemeld als gap, nooit als nul opgeslagen.
- Dubbele regel: één keer opgeslagen; bij verschillende waarden wint de nieuwste `created`.
- Boven de limiet (KV 13,8 / GV 43,3 kWh per kwartier): opgeslagen met waarschuwing.
- Ontbrekende kolom of leeg bestand: hele import mislukt.
- Hetzelfde bestand opnieuw: `duplicate` / `409`.

## Simultaneity

After every successful import the period of that import is recalculated from **all** meters in the database (not only the meters in the file), one week at a time, and replaced in `community_simultaneity`. Running it again gives the same result.

```
total_to_grid   = sum of to_grid_kwh   of all meters in the quarter
total_from_grid = sum of from_grid_kwh of all meters in the quarter
shared          = min(total_to_grid, total_from_grid)
KPI over period = sum(shared) / sum(total_to_grid)
```

- **Per quarter hour, not per day.** `min()` is not additive: calculating per day lets energy generated at 13:00 be used at 20:00 (as if there were a battery) and gives a number that is too high. Day, week and month are sums of quarters, for example `GROUP BY time_bucket('1 day', ts)`. Never average daily percentages.
- No netting per meter: feed-in and consumption are summed separately.
- A quarter without readings gets no row (a gap, not 0). If one meter is missing it does not count; `meter_count` shows how complete the quarter is.
- Calculated with `Decimal`, so the CHECK `shared = LEAST(...)` always holds exactly.
- The share of a participant is not stored; `pro_rata()` calculates it on request (`own consumption / total consumption × shared`, and the same for feed-in).
- If the recalculation fails, the import still succeeds (the readings are stored) with a warning `simultaneity_failed`. Recover with `--recalculate`.

## Gebruik

In de dev-container staan `BACKEND_API_URL` en `SES_TOKEN_PROCESSING` al klaar (`compose.yaml`) en draait de Backend API als eigen container.

```bash
cd services/data-processing-service

python -m data_processing_service tests/fixtures/testset_wintertijd_2026.csv     # importeren
python -m data_processing_service ../../data/meterdata.csv --validate-only       # alleen controleren
python -m data_processing_service --recalculate 2026-06-01 2026-07-01            # recalculate simultaneity (UTC)
uvicorn data_processing_service.import_endpoint:app --host 0.0.0.0 --port 8000   # API, docs op /docs
pytest -v                                                                        # tests
```

## Backend API

`backend_client.py` gebruikt de Backend API (`services/backend-api`) in deze volgorde:

1. `POST /v1/imports`: import registreren in `import_log` (`409` = bestand al geïmporteerd)
2. `GET /v1/meters` en `POST /v1/meters`: nieuwe meters toevoegen (readings verwijst ernaar)
3. `PUT /v1/readings`: metingen upserten, per 10.000 rijen
4. `PATCH /v1/imports/{id}`: status, periode, aantal rijen en nieuwe meters
5. `GET /v1/readings?start&end` and `PUT /v1/simultaneity`: recalculate the simultaneity of the import period, one week at a time

Gaat er iets mis, dan wordt de import in `import_log` op `failed` gezet met de foutmelding.

De unit tests gebruiken een nagebootste Backend API. `test_integratie_met_backend_api` importeert de testset in de echte database van de dev-container en ruimt die daarna op; buiten de dev-container wordt die test overgeslagen.
