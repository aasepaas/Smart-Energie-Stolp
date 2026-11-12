# Smart Energie Stolp (SES): project context

This file describes what SES is, why it exists and what the target architecture looks like.
Read it before making any change. Development rules are in [DEV.md](DEV.md).

## 1. Background

| Item | Value |
| --- | --- |
| Project | Fourth-year HBO graduation project (Networks and Systems Engineering, IoT), team of two students |
| Client | Energiek Alphen aan den Rijn |
| Community | Energy community EG Benthuizen, project "Energie Stolp" |
| Participants | 39 residents, companies and organisations that gave consent to use their energy data |
| System name | Smart Energie Stolp, abbreviated **SES** (also the id in the C4 model and the Jira key) |
| Repository | `aasepaas/Smart-Energie-Stolp` on GitHub |
| Planning | Research and design resulting in a Proof of Concept (PoC), then 5 implementation sprints, ending in a demo |

### Problem

Only 45 to 50 percent of the energy generated locally inside the Energie Stolp is also consumed locally.
The rest is fed into the grid while, at other moments, participants take energy from the grid.

### Goal

Increase the **simultaneity** of local generation and consumption from 45 to 50 percent towards 70 to 80 percent,
while keeping comfort and ease of use for participants. The largest gain is in shifting large appliances
(electric transport, heat pumps, air conditioning), including at small businesses with large consumers.

### Solution

1. A **web portal** that visualises consumption, generation and simultaneity for the whole community.
2. **Personal advice** per participant: every evening a top 3 of concrete suggestions to shift consumption to tomorrow's expected surplus.
3. **Machine learning** forecasts generation and consumption per quarter hour; an optimiser schedules flexible appliances into the forecast surplus.

## 2. Domain

### Input data

- The grid operator delivers pseudonymised **quarter-hourly readings per meter** as a CSV export.
- The administrator downloads the export manually a few times per year and uploads it in the web app.
- Relevant CSV columns: `meter_reference`, `interval_start`, `interval_time`, `to_grid_kWh` (feed-in), `from_grid_kWh` (consumption), `created`, `nl_date`, `nl_time`.
- Values use a **decimal comma** and can be quoted.
- `meter_reference` looks like `KV01` (small connection), `GV03` (large connection) or `meter_` plus 24 hex characters.
- The client builds its own tool to link changing meter ids to each other; SES does not solve that.

### Rules for meter data

- Time comes from `interval_start` + `interval_time` (already UTC). `nl_date` and `nl_time` are only a check, because 02:00 to 03:00 local time occurs twice when daylight saving time ends.
- All timestamps are `timestamptz` in **UTC**, resolution is **one quarter hour**, the timestamp is the **start** of the quarter.
- A missing quarter is a **missing row**, never a zero.
- A duplicate row is stored once; with different values the newest `created` wins.
- Values above the limit (KV 13.8 kWh, GV 43.3 kWh per quarter) are stored with a warning.
- Importing the same file twice is refused (SHA-256 hash in `import_log`, HTTP `409`).
- Readings are upserted on `(meter_reference, ts)`, so a re-import never creates duplicates.
- A new `meter_reference` is created automatically on import; the administrator links it to a participant in the admin panel. A participant can have several meters.

### Simultaneity

Simultaneity is calculated for the **whole Stolp**, per quarter hour, over all meters (independent of the link to participants):

```
total_to_grid   = sum(to_grid_kwh)   of all meters in the quarter
total_from_grid = sum(from_grid_kwh) of all meters in the quarter
shared_kwh      = min(total_to_grid, total_from_grid)

KPI over a period = sum(shared_kwh) / sum(total_to_grid)
```

The share of one participant is not stored; it is calculated on request as
`participant from_grid / total_from_grid * shared_kwh`.

### Users and roles

| Application role | Who | Can do |
| --- | --- | --- |
| `participant` | Participant | View own data, forecasts and advice, give feedback, edit own comfort limits |
| `viewer` | Client, supervisors | View community simultaneity and prices only |
| `administrator` | Community administrator | Upload CSV, link meters, manage participants, appliances, accounts and settings |
| `superadmin` | Technical administrator | Everything an administrator can, plus managing admin accounts |

The full permission matrix (application roles and database roles) is in [`database/roles/readme.md`](database/roles/readme.md).

## 3. Target architecture

The architecture is modelled with the C4 model (levels 1 to 3) in LikeC4:
[`architecture/ses_v0.1_en.c4`](architecture/ses_v0.1_en.c4). Exported views are in `architecture/exports/`.
**The C4 model is the source of truth.** If code and model disagree, ask the team before changing either.

### Level 1: context

```
Participant ──HTTPS──▶ ┌───────────────────────┐ ──HTTPS──▶ Weather service (48 h forecast)
Administrator ─HTTPS─▶ │  Smart Energie Stolp  │ ──HTTPS──▶ Apex data API (day-ahead prices)
                       └───────────────────────┘ ┄┄┄┄┄┄┄┄▶ Community battery (optional, not in PoC)
Administrator ┄┄ manual CSV download ┄┄▶ Grid operator
```

### Level 2: containers

All containers run with Docker Compose on a local server.

| Container | Technology | Responsibility |
| --- | --- | --- |
| **Web app** | React, TypeScript | SPA for participants and administrators: dashboards, advice, CSV upload, settings. Talks only to the Frontend API. |
| **Frontend API** | Python, FastAPI | Single entry point for the web app. Verifies JWT, role and data ownership, queries the database with the frontend role, forwards CSV uploads to the Data processing service. |
| **Backend API** | Python, FastAPI, psycopg | Internal API between the backend services and the database. Service token per container, switches to a database role per request. |
| **Data processing service** | Python, FastAPI, pandas | Imports meter data idempotently, links meters, calculates simultaneity, triggers training. |
| **Ingest and training pipeline** | Python, PyCaret, scikit-learn, XGBoost | After every import: measures the effect of advice, builds features, selects and trains models, promotes a model only if it beats production. |
| **Forecast pipeline** | Python, scikit-learn, XGBoost, PuLP (HiGHS) | Every evening at 20:00 (after the day-ahead prices are published at 15:00): fetches prices and weather, forecasts P10/P50/P90, optimises appliance schedules, ranks the top 3 advice per participant. |
| **Model registry** | MLflow | Model versions, training runs and scores. The forecast pipeline only uses versions with alias `production`. |
| **Database** | PostgreSQL 17 with TimescaleDB | Readings, meters, simultaneity, forecasts, prices, advice, accounts and settings. |

### Allowed communication paths

Only these paths exist. Do not add a new one without updating the C4 model first.

| From | To | How |
| --- | --- | --- |
| Web app | Frontend API | HTTPS, REST/JSON and multipart, Bearer JWT |
| Frontend API | Data processing service | HTTP `POST /imports` (multipart) |
| Frontend API | Database | SQL, login role `ses_frontend` |
| Data processing service | Backend API | HTTP REST/JSON |
| Data processing service | Ingest and training pipeline | HTTP `POST /training-runs`, asynchronous |
| Ingest and training pipeline | Backend API | HTTP REST/JSON |
| Ingest and training pipeline | Model registry | MLflow REST API |
| Forecast pipeline | Backend API | HTTP REST/JSON |
| Forecast pipeline | Model registry | MLflow REST API |
| Forecast pipeline | Weather service, Apex data API | HTTPS REST/JSON |
| Backend API | Database | SQL, login role `ses_backend` |

Consequences:

- Only the **Frontend API** and the **Backend API** connect to the database.
- The processing, training and forecast containers reach the database **only through the Backend API**, each through one `backend_client` module.
- The web app never talks to anything other than the Frontend API.

### Level 3: components per container

| Container | Components (planned module names) |
| --- | --- |
| Web app | `app/` (router, layout, route guards), `auth/`, `features/data-view/`, `features/data-import/`, `features/settings/`, `api/` |
| Frontend API | API endpoints, authentication, query builder, query executor, upload handler |
| Backend API | API endpoints (routers), authentication (service token), query builder, query executor |
| Data processing service | `import_endpoint`, `import_orchestrator`, `csv_parser`, `validator`, `meter_linker`, `simultaneity_calculator`, `backend_client`, `training_notifier` |
| Ingest and training pipeline | `training_orchestrator`, `effect_measurement`, `feature_builder`, `model_selector`, `model_trainer`, `model_evaluator`, `backend_client` |
| Forecast pipeline | `scheduler`, `price_client`, `weather_client`, `model_loader`, `forecaster`, `optimizer`, `ranker`, `backend_client` |

### Database

Design: [`database/erd/ses-database.dbml`](database/erd/ses-database.dbml). Schema, roles and row-level security: Alembic migrations in `database/migrations/`.

| Group | Tables |
| --- | --- |
| Accounts | `participants`, `users`, `participant_appliances`, `settings` |
| Meter data | `import_log`, `meters`, `readings` |
| Results | `community_simultaneity`, `forecasts`, `energy_prices`, `advice` |

- Hypertables (TimescaleDB): `readings`, `community_simultaneity`, `forecasts`, `energy_prices`.
- The database starts as simple as possible: only data that is really needed, while still supporting every function in the C4 model.
- Each service has its own database role; permissions are enforced in PostgreSQL with `GRANT` and row-level security.

### Machine learning

- Forecasts per quarter hour with quantiles **P10, P50, P90** for generation and consumption.
- Model selection with PyCaret `compare_models`, training as quantile forecasters (scikit-learn or XGBoost).
- Evaluation on a hold-out period with pinball loss and MAE; a candidate is promoted only if it beats the production model.
- No lag features of yesterday (data arrives only a few times per year).
- The optimiser plans into the **P10** surplus within the comfort limits of each appliance.
- The ranker classifies advice as high, medium or low impact by expected shared kWh and ranks by impact times the chance of being followed; the price only adds a small weight.
- Effect measurement compares actual consumption with the P50 forecast.

## 4. Current status

| Part | Status |
| --- | --- |
| Dev container (TimescaleDB, MLflow, Backend API) | Working |
| Database schema, roles, RLS (migration `0001`) | Working |
| Backend API | Working, endpoints listed in `services/backend-api/README.md` |
| Data processing service | Import, parser, validator and simultaneity calculator (recalculated after each import) working; meter linker and training notifier still to do |
| Frontend API, Web app | Not started (README only) |
| Training pipeline, Forecast pipeline | Not started (README only) |
| `packages/ses-common` | Not started (README only) |

Sprint 1 focus: database, Backend API, model registry (possibly with a simulated model) and a simple forecast pipeline.

### Known discrepancies

These are known and should be fixed in their own ticket, not as a side effect of another change.

- `services/README.md` mentions `processing-service/`; the folder is `data-processing-service/`.
- `services/frontend-api/README.md` and the port label in `.devcontainer/devcontainer.json` still say Flask; the decision is FastAPI.
- The C4 model mentions tables `meter_links` and per-participant `simultaneity`; the DBML (leading for the database) uses `meters` and `community_simultaneity`.
- Several READMEs, comments, test names and fixtures are still in Dutch; everything must become English (see DEV.md).
- `data-processing-service` uses hatchling and Python `>=3.10`; the standard is setuptools and Python `>=3.12`.
- Each service has its own backend client; this should move to `packages/ses-common`.
