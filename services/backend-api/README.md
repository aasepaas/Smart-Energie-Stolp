# SES Backend API

Interne API tussen de backend-services (Data processing service, Ingest and training pipeline, Forecast pipeline) en de database. Gebouwd met FastAPI en psycopg.

## Hoe het werkt

```
service  ──Bearer token──▶  Backend API  ──ses_backend──▶  PostgreSQL
                              │                              │
                   1. token → welke service     3. SET LOCAL ROLE svc_...
                   2. mag deze service dit      4. query met de rechten
                      endpoint gebruiken?          van die rol
```

Elk verzoek wordt twee keer gecontroleerd:

1. **In de API:** het service token bepaalt welke service het is, en elk endpoint zegt welke services het mogen gebruiken. Anders: `403`.
2. **In de database:** de API logt in als `ses_backend` en wisselt per verzoek naar `svc_processing`, `svc_training` of `svc_forecast`. Laat de API door een fout toch iets door, dan weigert de database alsnog (ook `403`).

Elk verzoek is één transactie: lukt alles, dan wordt het vastgelegd; gaat er iets mis, dan wordt alles teruggedraaid.

## Endpoints

Alle endpoints staan onder `/v1`. De interactieve documentatie staat op `/docs`.

| Methode | Pad | processing | training | forecast | Doel |
|---|---|:-:|:-:|:-:|---|
| GET | `/meters` | ✓ | ✓ | ✓ | Meters met gekoppelde deelnemer |
| POST | `/meters` | ✓ | | | Nieuwe meters toevoegen |
| GET | `/readings?start&end&meter_reference` | ✓ | ✓ | ✓ | Metingen in een periode |
| PUT | `/readings` | ✓ | | | Metingen wegschrijven (upsert) |
| POST | `/imports` | ✓ | | | Import registreren; dezelfde CSV geeft `409` |
| PATCH | `/imports/{id}` | ✓ | | | Importresultaat bijwerken |
| GET | `/simultaneity?start&end` | ✓ | ✓ | ✓ | Gelijktijdigheid per kwartier |
| PUT | `/simultaneity` | ✓ | | | Periode herberekenen |
| GET | `/forecasts?start&end&run_date` | | ✓ | ✓ | Voorspellingen |
| POST | `/forecasts` | | | ✓ | Voorspellingen toevoegen |
| GET | `/energy-prices?start&end` | | | ✓ | Day-ahead-prijzen |
| PUT | `/energy-prices` | | | ✓ | Prijzen wegschrijven (upsert) |
| GET | `/advice?start_date&end_date` | | ✓ | ✓ | Advies met feedback en effect |
| PUT | `/advice` | | | ✓ | Top-3-advies van een dag; behoudt feedback |
| PATCH | `/advice/effects` | | ✓ | | Gemeten effect vastleggen |
| GET | `/participants` | | ✓ | ✓ | Deelnemers |
| GET | `/appliances` | | | ✓ | Apparaten en comfortgrenzen |
| GET | `/settings` | ✓ | ✓ | ✓ | Systeeminstellingen |
| GET | `/health` | – | – | – | Controle voor Docker, zonder token |

Schrijfverzoeken accepteren maximaal 10.000 rijen; stuur grotere imports in delen. Alle tijden moeten een tijdzone hebben (bijvoorbeeld `2026-06-01T12:00:00+00:00`), anders `422`.

## Starten

In de dev-omgeving start de Backend API automatisch als eigen container (`backend-api` in `.devcontainer/compose.yaml`), zodra de dev-container opent. Wijzigingen in `src/` worden direct opgepikt (`--reload`).

| Vanaf | Adres |
|---|---|
| De dev-container en de andere services | `http://backend-api:8001` (ook in `BACKEND_API_URL`) |
| Je eigen computer (browser) | `http://localhost:8001/docs` |

De service tokens voor de dev-omgeving staan in `compose.yaml` (`dev-processing`, `dev-training`, `dev-forecast`). Gebruik op de server echte tokens via een `.env`-bestand; maak ze aan met:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Logs bekijken:

```bash
docker compose -p ses-dev logs -f backend-api
```

## Een service aanroepen

```python
import httpx

import os

api = httpx.Client(base_url=os.environ["BACKEND_API_URL"],
                   headers={"Authorization": f"Bearer {os.environ['SES_TOKEN_FORECAST']}"})
api.put("/energy-prices", json=[{"ts": "2026-11-05T00:00:00+01:00", "price_eur_per_kwh": "0.21"}])
```

## Testen

De tests draaien tegen de echte database (met het schema en `rollen_en_rechten.sql`), maken eigen testdata aan en ruimen die daarna op.

In de terminal van de dev-container staat alles al klaar:

```bash
cd services/backend-api
pytest -v
```
