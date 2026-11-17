# SES Frontend API

Single entry point for the web app (container **Frontend API**, C4 view 3.2). Built with FastAPI and psycopg, in the same way as the Backend API.

- logs users in and issues JWTs;
- checks the role and whether the user may see the requested data;
- answers queries directly from the database with login role `ses_frontend`;
- forwards CSV uploads to the Data processing service (`POST /imports`).

## How it works

```
web app ──Bearer JWT──▶ Frontend API ──ses_frontend──▶ PostgreSQL
                          │                               │
              1. JWT → user, role, participant   3. SET LOCAL ROLE web_participant | web_admin
              2. may this role use the endpoint,    SET LOCAL app.participant_id = <own id>
                 and only for its own data?      4. GRANTs and row-level security check again
```

Every request is checked twice:

1. **In the API:** the access token gives the user, the role and (for a participant) the participant id. Each endpoint lists the roles that may use it (`403` otherwise), and `participant_scope` limits a participant to their own data.
2. **In the database:** the API switches to `web_participant` (participant, viewer) or `web_admin` (administrator, superadmin) and sets `app.participant_id`. Row-level security only returns a participant's own rows; a viewer has no participant id and only sees community data. If the API lets something through by mistake, the database still refuses it (also `403`) or returns nothing (`404`).

Every request is one transaction that commits before the response is sent (`Depends(get_session, scope="function")`).

### Components

| Module | C4 component |
| --- | --- |
| `endpoints/` | API endpoints: one router per resource, Pydantic validation |
| `authentication.py` | Authentication: Argon2 password check, JWTs, roles, data ownership |
| `query_builder.py` | Query builder: all SQL, parameterised, limited to the caller's data |
| `query_executor.py` | Query executor: connection pool, transaction, role switch per request |
| `upload_handler.py` | Upload handler: checks the CSV and forwards it to the processing service |

## Authentication

| Token | Lifetime | Where |
| --- | --- | --- |
| Access token (JWT, HS256) | 15 minutes (`ACCESS_TOKEN_MINUTES`) | In the web app's memory, sent as `Authorization: Bearer <token>` |
| Refresh token (JWT, HS256) | 7 days (`REFRESH_TOKEN_HOURS`) | HttpOnly cookie `ses_refresh`, `SameSite=Strict`, path `/v1/auth` |

Logging in calls the database function `auth_user_by_email` (no role can read `password_hash`) and checks the Argon2 hash in the API. A refresh loads the account again, so a changed role or a deleted account takes effect within one access token lifetime. Logout removes the cookie; an access token stays valid until it expires.

## Endpoints

All endpoints are under `/v1`. Interactive documentation: `/docs`. P = participant, V = viewer, A = administrator, S = superadmin.

| Method | Path | P | V | A | S | Purpose |
|---|---|:-:|:-:|:-:|:-:|---|
| POST | `/auth/login` | – | – | – | – | Email and password → access token and refresh cookie |
| POST | `/auth/refresh` | – | – | – | – | New access token from the refresh cookie |
| POST | `/auth/logout` | – | – | – | – | Removes the refresh cookie |
| GET | `/auth/me` | ✓ | ✓ | ✓ | ✓ | The logged in user |
| GET | `/simultaneity?start&end&bucket` | ✓ | ✓ | ✓ | ✓ | Community simultaneity with totals for the period |
| GET | `/prices?start&end` | ✓ | ✓ | ✓ | ✓ | Dynamic day-ahead prices |
| GET | `/readings?start&end&bucket&participant_id` | own | | ✓ | ✓ | Consumption, feed-in and share of shared energy per participant |
| GET | `/forecasts?start&end&participant_id` | own | | ✓ | ✓ | Latest P10/P50/P90 forecast per quarter hour |
| GET | `/advice?start_date&end_date&participant_id` | own | | ✓ | ✓ | Top 3 advice with feedback and measured effect |
| PUT | `/advice/{id}/feedback` | own | | | | Accept or reject advice |
| GET | `/appliances?participant_id` | own | | ✓ | ✓ | Appliances and comfort limits |
| PATCH | `/appliances/{id}` | own | | ✓ | ✓ | Change comfort limits |
| POST, DELETE | `/appliances`, `/appliances/{id}` | | | ✓ | ✓ | Add or remove an appliance |
| GET | `/participants` | own | | ✓ | ✓ | Participants with their meters |
| POST, PATCH, DELETE | `/participants`, `/participants/{id}` | | | ✓ | ✓ | Manage participants |
| GET | `/meters?unlinked` | own | | ✓ | ✓ | Meters with participant and last reading |
| PUT | `/meters/{meter_reference}/participant` | | | ✓ | ✓ | Link a meter to a participant (or unlink with `null`) |
| POST | `/uploads?validate_only` | | | ✓ | ✓ | Upload a CSV export (multipart, field `file`) |
| GET | `/uploads`, `/uploads/{id}` | | | ✓ | ✓ | Imports with status and result (`import_log`) |
| GET | `/settings` | | | ✓ | ✓ | System settings |
| PUT | `/settings/{key}` | | | ✓ | ✓ | Create or replace a setting (any JSON value) |
| GET | `/users` | | | ✓ | ✓ | Accounts (never the password hash) |
| POST, PATCH, DELETE | `/users`, `/users/{id}` | | | ✓ ¹ | ✓ | Manage accounts |
| GET | `/health` | – | – | – | – | Check for Docker, without a token |

1. An administrator manages participant and viewer accounts; administrator and superadmin accounts only by a superadmin. Nobody can delete their own account or change their own role.

Rules for data requests:

- All times need a time zone (`2026-06-01T00:00:00+02:00`), otherwise `422`. Periods are `[start, end)` and at most 366 days (`MAX_PERIOD_DAYS`).
- `bucket` is `quarter` (default), `hour`, `day` or `month`. Days and months follow Dutch local time, so a day starts at 22:00 or 23:00 UTC.
- `quarter_count` tells how many quarters with data are in a bucket; fewer than expected means gaps (missing quarters are never zero).
- `shared_kwh` in `/readings` is the participant's share: participant from_grid / total from_grid × community shared_kwh per quarter, summed per bucket.
- A participant who asks for another `participant_id` gets `403`; advice or appliances of someone else give `404`.

Uploads: the file must end in `.csv`, be non-empty and at most 200 MB (`MAX_UPLOAD_BYTES`). The answer of the processing service is passed on: `202` with `import_id` (follow it with `GET /uploads/{import_id}`), `200` with the report for `validate_only=true`, `409` for a file that was imported before. If the processing service cannot be reached: `503` (`504` on a timeout, `502` on an error). Put a body size limit on the reverse proxy as well; the API only checks the size after receiving the file.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FRONTEND_DATABASE_URL` | `postgresql://ses_frontend:user@db:5432/ses` | Database, login role `ses_frontend` |
| `SES_JWT_SECRET` | – (required, ≥ 32 characters) | Signs the JWTs |
| `ACCESS_TOKEN_MINUTES` | `15` | Lifetime of the access token |
| `REFRESH_TOKEN_HOURS` | `168` | Lifetime of the refresh token |
| `REFRESH_COOKIE_SECURE` | `true` | `false` only for local http |
| `CORS_ORIGINS` | empty | Web app origins (comma separated), e.g. `http://localhost:5173` |
| `PROCESSING_SERVICE_URL` | `http://data-processing-service:8000` | Data processing service |
| `PROCESSING_TIMEOUT` | `300` | Seconds per upload request |
| `MAX_UPLOAD_BYTES` | `209715200` | Largest CSV upload |
| `MAX_PERIOD_DAYS` | `366` | Longest period per data request |
| `SES_TIMEZONE` | `Europe/Amsterdam` | Time zone for day and month buckets |

Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Running

```bash
cd services/frontend-api
SES_JWT_SECRET=dev-secret-of-at-least-thirty-two-chars \
FRONTEND_DATABASE_URL=postgresql://ses_frontend:user@db:5432/ses \
uvicorn frontend_api.main:app --host 0.0.0.0 --port 8002 --reload
```

Then open `http://localhost:8002/docs`. The first account has to be created directly in the database (as `ses` or `ses_dba`), with a hash from `python -c "from frontend_api.authentication import hash_password; print(hash_password('...'))"`.

## Testing

The unit tests (`test_authentication.py`, `test_uploads.py`) need no database. `test_api.py` runs against the real database with migration `0001`, creates its own data and removes it afterwards.

```bash
cd services/frontend-api
pytest -v
```

## Known limitations

- The database enum `user_role` only has `participant` and `administrator`. The API supports `viewer` and `superadmin`, but such accounts can only be created after a migration adds them (until then: `422`).
- The detailed import report (issues per line) only exists in the processing service; `GET /uploads/{id}` shows status and counts from `import_log`.
- No rate limiting on `/auth/login` yet.
