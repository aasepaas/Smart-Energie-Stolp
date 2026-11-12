# Development guide

Rules and instructions for everyone who works on this repository, human or AI agent.
Read [CONTEXT.md](CONTEXT.md) first for what the system is and how the architecture is meant to look.

If a rule here conflicts with a request, ask before acting.

## 1. Language

**Everything in the repository is in English.** This includes:

- code: identifiers, function, class, variable and file names;
- comments and docstrings;
- READMEs and other documentation;
- commit messages, branch names and pull request texts;
- log messages, error messages and API responses;
- test names and test fixture names;
- the C4 model and the DBML.

When you touch a file that still contains Dutch, translate the part you change. Translating a whole file is its own ticket.

## 2. Branch strategy

`main` is the stable branch. All work happens on a short-lived branch per Jira ticket.

### Branch names

```
<type>/ses-<ticket-number>-<short-description>
```

- lowercase only, words separated by hyphens (kebab-case), no underscores;
- `<ticket-number>` is the number of the Jira issue (`SES-214` becomes `ses-214`);
- `<short-description>` is two to five words.

| Type | Use for | Example |
| --- | --- | --- |
| `feature/` | New functionality | `feature/ses-12-data-processing-service` |
| `bugfix/` | Fixing a bug | `bugfix/ses-231-dst-duplicate-quarters` |
| `setup/` | Tooling, dev container, infrastructure | `setup/ses-200-devcontainer` |
| `docs/` | Documentation only | `docs/ses-240-context-and-dev-guide` |
| `refactor/` | Restructuring without changing behaviour | `refactor/ses-245-move-backend-client` |
| `test/` | Adding or fixing tests only | `test/ses-250-import-edge-cases` |

### Workflow

1. Pick or create a Jira issue (Epic, Story, Task or Bug).
2. Branch off the latest `main`.
3. Commit small, focused changes.
4. Open a pull request to `main` and reference the ticket (`SES-<number>`).
5. Delete the branch after the merge.

One branch covers one ticket. Do not mix unrelated changes in one branch.

## 3. Repository structure

```
.
├── CONTEXT.md                  project context and target architecture
├── DEV.md                      this file
├── README.md
├── .devcontainer/              development environment (see section 4)
├── architecture/               C4 model in LikeC4 (source of truth for the architecture)
│   ├── ses_v0.1_en.c4          the model, levels 1 to 3
│   ├── likec4.config.json
│   ├── .likec4/                manually adjusted view layouts
│   ├── export-views.mjs        exports all views to PNG
│   └── exports/                exported views
├── data/                       local meter data exports, ignored by git (except README.md)
├── database/
│   ├── alembic.ini
│   ├── erd/                    database design in DBML (leading for the schema)
│   ├── init/                   SQL run once on an empty database (extensions)
│   ├── migrations/             Alembic migrations: schema, roles, grants, RLS
│   ├── roles/                  role and permission design plus test
│   └── seed/                   fake data for development, tests and the demo
├── docs/                       project documents (requirements, plan, research, test plan)
├── model-registry/             MLflow server
├── packages/
│   └── ses-common/             shared Python package for the backend containers
├── services/                   one folder per backend container
│   ├── backend-api/
│   ├── data-processing-service/
│   ├── frontend-api/
│   ├── training-pipeline/
│   │   └── notebooks/          exploration only, no production code
│   └── forecast-pipeline/
└── web-app/                    React + TypeScript SPA
```

### Service layout

Every Python service uses the same layout:

```
services/<service-name>/
├── pyproject.toml              setuptools, requires-python ">=3.12", optional "dev" extra
├── Dockerfile                  python:3.12-slim, runs as non-root user, has a HEALTHCHECK
├── README.md                   purpose, endpoints, how to run and test
├── src/<package_name>/
│   ├── __init__.py
│   ├── config.py               all settings from environment variables
│   └── ...                     one module per C4 component
└── tests/
    ├── fixtures/               invented test data only
    └── test_*.py
```

- Folder names are kebab-case (`data-processing-service`), Python packages and modules are snake_case (`data_processing_service`).
- Module names follow the component names in the C4 model (see CONTEXT.md, level 3).

### Shared code

Code that is needed in two or more services goes into `packages/ses-common` (package `ses_common`), not copied between services.
Examples: the Backend API client, time and quarter-hour helpers, Pydantic schemas shared between services, config helpers.

### Configuration

- URLs, ports, tokens, passwords, file paths and limits are read from **environment variables** in the service's `config.py` only.
- No hardcoded hosts, ports or credentials anywhere else in the code.
- Development values live in `.devcontainer/compose.yaml`; server values come from an `.env` file that is never committed.

## 4. Dev container

Development happens inside the VS Code dev container. Setup and troubleshooting: [`.devcontainer/README.md`](.devcontainer/README.md).

### How it is built

| File | Purpose |
| --- | --- |
| `devcontainer.json` | Uses `compose.yaml`, attaches VS Code to service `dev`, adds Node 22 and Docker-outside-of-Docker, installs VS Code extensions (Python, Pylance, Ruff, Jupyter, ESLint, Prettier, LikeC4) |
| `compose.yaml` | Compose project `ses-dev` with the services below |
| `Dockerfile` | Work container based on `mcr.microsoft.com/devcontainers/python:1-3.12-bookworm`, adds `postgresql-client` and `libgomp1` |
| `post-create.sh` | Runs after every (re)build: installs Alembic and psycopg, `packages/ses-common` and every service with a `pyproject.toml` in editable mode with the `dev` extra, and `npm install` for the web app when it exists |

`postStartCommand` runs `alembic upgrade head` on every start, so new migrations are applied automatically after a pull.

### Services

| Service | Content | Inside the container | From the host |
| --- | --- | --- | --- |
| `dev` | Work container, Python 3.12 and Node 22 | | |
| `db` | PostgreSQL 17 with TimescaleDB 2.x | `db:5432` | `localhost:5432` |
| `mlflow` | MLflow tracking server and model registry | `http://mlflow:5000` | `http://localhost:5000` |
| `backend-api` | Backend API with `--reload` on `src/` | `http://backend-api:8001` | `http://localhost:8001/docs` |

Preset environment variables in `dev`: `DATABASE_URL`, `PG*` (so `psql` works without arguments), `MLFLOW_TRACKING_URI`, `ALEMBIC_CONFIG`, `BACKEND_API_URL`, `SES_TOKEN_*` and `SES_PASSWORD_*`.
These values are for local development only and are not secrets.

Data is stored in the volumes `ses-dev_db-data` and `ses-dev_mlflow-data`.

### Adding a new service to the dev container

1. Create the service with the standard layout (section 3).
2. Add it to `compose.yaml` with its own environment variables and `depends_on`.
3. Add it to `runServices` in `devcontainer.json` if it should start automatically.
4. Rebuild the container and document the change in `.devcontainer/README.md`.

### Common commands

```bash
alembic upgrade head                         # apply migrations
alembic current                              # show current revision
psql -c '\dt'                                # list tables
cd services/<service-name> && pytest -v      # run the tests of a service
docker compose -p ses-dev logs -f backend-api
cd architecture && npx likec4 start          # open the C4 model
```

## 5. Database changes

1. Change `database/erd/ses-database.dbml` first.
2. Add a new Alembic migration in `database/migrations/versions/` with the next number (`0002_add_x_to_y.py`), plain SQL in `op.execute`.
3. Put grants and RLS policies for new tables in the same migration and update the matrix in `database/roles/readme.md`.
4. DBML, migration and role changes go in the same pull request.

Never edit a migration that is already on `main`; always add a new one.
If two branches create a migration with the same `down_revision`, renumber one of them.

## 6. Data and secrets

- Never commit real meter data, not even pseudonymised. Use `data/` (ignored) for local exports and `database/seed/` or `tests/fixtures/` for invented data.
- Never commit notebook output that contains real meter data.
- Never commit secrets, tokens, `.env` files or production passwords.
- Never log tokens, passwords or full meter data rows.

## 7. Rules for AI agents

AI agents may read the whole repository, write code, run tests and create local commits on a correctly named branch. In addition to all rules above:

### Never

- push to any remote, on any branch;
- merge, rebase or open/close pull requests;
- commit real meter data, secrets or `.env` files.

### Ask first

Before doing any of the following, stop and ask for approval:

- adding, removing or upgrading a dependency;
- changing the database schema (DBML, migrations, roles, grants, RLS);
- adding, removing or changing a public endpoint (path, parameters, request or response shape) of any API;
- adding a communication path that is not in the C4 model;
- anything that conflicts with CONTEXT.md or this file.

### Always

- follow the language rule, the branch naming and the service layout above;
- keep changes limited to the ticket being worked on;
- run the tests of every service you changed inside the dev container and report the result;
- update the README of a service when its behaviour, endpoints or usage change.
