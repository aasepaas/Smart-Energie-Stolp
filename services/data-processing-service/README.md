# Data processing service

Container **Data processing service** (Python, FastAPI, pandas): importeert meterdata en berekent de gelijktijdigheid. Zie C4-view *3.3*.

## Opbouw

```
src/data_processing_service/
  import_endpoint.py      POST /imports, GET /imports/{id}
  import_orchestrator.py  voert de stappen in volgorde uit
  csv_parser.py           decimale komma, quotes, tijd naar UTC
  validator.py            dubbelen, gaps, limieten per meter
  backend_client.py       enige weg naar de Backend API (httpx)
  models.py               importrapport en meldingen
  config.py               limieten en instellingen
  __main__.py             handmatig importeren vanaf de command line
tests/
  test_*.py               unit tests
  fixtures/*.csv          verzonnen testdata met randgevallen
```

Later volgen `meter_linker.py`, `simultaneity_calculator.py` en `training_notifier.py`.

## Regels bij het inlezen

- Tijd komt uit `interval_start` + `interval_time` (al UTC). `nl_date`/`nl_time` zijn alleen controle, want bij wintertijd komt 02:00-03:00 lokaal twee keer voor.
- Foute regel (geen getal, leeg, ongeldige tijd, negatief): geweigerd, het kwartier wordt een gap.
- Ontbrekend kwartier: gemeld als gap, nooit als nul opgeslagen.
- Dubbele regel: één keer opgeslagen; bij verschillende waarden wint de nieuwste `created`.
- Boven de limiet (KV 13,8 / GV 43,3 kWh per kwartier): opgeslagen met waarschuwing.
- Ontbrekende kolom of leeg bestand: hele import mislukt.
- Hetzelfde bestand opnieuw: `duplicate` / `409`.

## Gebruik

In de dev-container staan `BACKEND_API_URL` en `SES_TOKEN_PROCESSING` al klaar (`compose.yaml`) en draait de Backend API als eigen container.

```bash
cd services/data-processing-service

python -m data_processing_service tests/fixtures/testset_wintertijd_2026.csv     # importeren
python -m data_processing_service ../../data/meterdata.csv --validate-only       # alleen controleren
uvicorn data_processing_service.import_endpoint:app --host 0.0.0.0 --port 8000   # API, docs op /docs
pytest -v                                                                        # tests
```

## Backend API

`backend_client.py` gebruikt de Backend API (`services/backend-api`) in deze volgorde:

1. `POST /v1/imports`: import registreren in `import_log` (`409` = bestand al geïmporteerd)
2. `GET /v1/meters` en `POST /v1/meters`: nieuwe meters toevoegen (readings verwijst ernaar)
3. `PUT /v1/readings`: metingen upserten, per 10.000 rijen
4. `PATCH /v1/imports/{id}`: status, periode, aantal rijen en nieuwe meters

Gaat er iets mis, dan wordt de import in `import_log` op `failed` gezet met de foutmelding.

De unit tests gebruiken een nagebootste Backend API. `test_integratie_met_backend_api` importeert de testset in de echte database van de dev-container en ruimt die daarna op; buiten de dev-container wordt die test overgeslagen.
