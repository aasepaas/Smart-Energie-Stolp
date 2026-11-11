# Data processing service

Container **Data processing service** (Python, FastAPI, pandas): importeert meterdata en berekent de gelijktijdigheid. Zie C4-view *3.3*.

## Opbouw

```
src/data_processing_service/
  import_endpoint.py      POST /imports, GET /imports/{id}
  import_orchestrator.py  voert de stappen in volgorde uit
  csv_parser.py           decimale komma, quotes, tijd naar UTC
  validator.py            dubbelen, gaps, limieten per meter
  backend_client.py       weg naar de Backend API (nu: dry-run)
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

```bash
pip install -e "services/data-processing-service[dev]"
cd services/data-processing-service

python -m data_processing_service tests/fixtures/testset_wintertijd_2026.csv     # importeren
python -m data_processing_service ../../data/meterdata.csv --validate-only       # alleen controleren
uvicorn data_processing_service.import_endpoint:app --host 0.0.0.0 --port 8000   # API, docs op /docs
pytest -v                                                                        # tests
```

## Backend API

De Backend API staat nog niet op main. `backend_client.py` volgt het contract van branch `ses-214-backend_api` (`/v1/meters`, `/v1/readings`, `/v1/imports`). Tot die klaar is schrijft de dry-run backend elk verzoek als JSON naar `data/dryrun/<import_id>/` (staat in `.gitignore`). Opnieuw beginnen: verwijder `data/dryrun`.
