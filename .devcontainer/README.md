# Dev container

Ontwikkelomgeving voor VS Code (Dev Containers). Openen met **Dev Containers: Reopen in Container**; Docker Desktop moet WSL-integratie aan hebben voor deze distro.

| Service | Inhoud | Bereikbaar in de werkcontainer | Vanaf de host |
| --- | --- | --- | --- |
| `dev` | werkcontainer met Python 3.12 en Node 22 | | |
| `db` | PostgreSQL 17 met TimescaleDB | `db:5432` | `localhost:5432` |
| `mlflow` | MLflow tracking server en model registry | `http://mlflow:5000` | `http://localhost:5000` |

- Database en gebruiker heten `ses` (wachtwoord `ses`), alleen voor lokaal gebruik. `DATABASE_URL`, de `PG*`-variabelen en `MLFLOW_TRACKING_URI` staan al klaar, dus `psql` werkt zonder argumenten.
- De SQL uit `database/init/` draait bij de eerste start van een lege database. Opnieuw beginnen: container sluiten en het volume `ses-dev_db-data` verwijderen.
- MLflow bewaart runs in SQLite en artefacten op het volume `ses-dev_mlflow-data`. Dit is de ontwikkelversie; de echte registry komt in `model-registry/`.
- `post-create.sh` installeert `packages/ses-common`, de services (editable) en de `node_modules` van de web app, voor zover die al bestaan. Na het toevoegen van een `pyproject.toml` of `package.json`: **Rebuild Container** of het script opnieuw draaien.
- Docker (outside of Docker) is beschikbaar, zodat je vanuit de werkcontainer ook service-images kunt bouwen.

Gebruik hier alleen nepdata uit `database/seed/` of lokale exports in `data/`; die staan niet in git.
