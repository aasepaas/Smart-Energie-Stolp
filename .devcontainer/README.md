# Dev container

Ontwikkelomgeving voor VS Code (Dev Containers). Eén commando start een werkcontainer met Python en Node, de database en de model registry, en zet het databaseschema klaar.

## Eenmalig instellen

1. Installeer **Docker Desktop** en zet in **Settings > Resources > WSL integration** je distro (bijvoorbeeld Ubuntu) aan.
2. Installeer in VS Code de extensies **WSL** en **Dev Containers**.
3. Clone de repo in WSL, niet in een Windows-map. Dat is sneller en voorkomt Windows-regeleinden in de scripts:
   ```bash
   git clone https://github.com/aasepaas/Smart-Energie-Stolp.git ~/Smart-Energie-Stolp
   ```

## Starten

1. Start Docker Desktop en wacht tot linksonder **Engine running** staat.
2. Open de repo vanuit WSL:
   ```bash
   cd ~/Smart-Energie-Stolp
   code .
   ```
3. `Ctrl+Shift+P` en kies **Dev Containers: Reopen in Container**. Kies **Rebuild and Reopen in Container** de eerste keer, en na elke wijziging in `.devcontainer/`.

Controle in de terminal van de container:

```bash
alembic current   # verwacht: <laatste revisie> (head)
psql -c '\dt'                             # alle tabellen
```

## Wat er draait

| Service | Inhoud | Bereikbaar in de werkcontainer | Vanaf de host |
| --- | --- | --- | --- |
| `dev` | werkcontainer met Python 3.12 en Node 22 | | |
| `db` | PostgreSQL 17 met TimescaleDB | `db:5432` | `localhost:5432` |
| `mlflow` | MLflow tracking server en model registry | `http://mlflow:5000` | `http://localhost:5000` |

- Database en gebruiker heten `ses` (wachtwoord `ses`), alleen voor lokaal gebruik. `DATABASE_URL`, de `PG*`-variabelen en `MLFLOW_TRACKING_URI` staan klaar, dus `psql` werkt zonder argumenten.
- De werkcontainer wacht tot de database healthy is.
- Docker (outside of Docker) is beschikbaar, zodat je vanuit de werkcontainer service-images kunt bouwen.

## Wat er gebeurt bij het aanmaken

`post-create.sh` draait na elke (re)build en installeert alleen wat al bestaat:

1. Alembic en psycopg, voor de databasemigraties;
2. `packages/ses-common` en elke service met een `pyproject.toml`, editable;
3. de `node_modules` van de web app, als er een `package.json` is.

Bij **elke start** van de container draait daarna `alembic upgrade head` (`postStartCommand`), zodat nieuwe migraties na een `git pull` vanzelf worden toegepast.

## Data en opnieuw beginnen

- De database staat in het volume `ses-dev_db-data`, MLflow in `ses-dev_mlflow-data`. Ze blijven bewaard als je de container sluit.
- De SQL in `database/init/` draait alleen bij de eerste start van een lege database (extensies en rollen). Het schema zelf komt uit de Alembic-migraties.
- Database leegmaken zonder het volume te verwijderen: `alembic downgrade base` en daarna `upgrade head`.
- Helemaal opnieuw beginnen: container sluiten, `docker volume rm ses-dev_db-data` en **Rebuild and Reopen in Container**.

Gebruik alleen nepdata uit `database/seed/` of lokale exports in `data/`; die staan niet in git.

## Problemen

| Melding | Oplossing |
| --- | --- |
| `The command 'docker' could not be found in this WSL 2 distro` | WSL integration voor je distro aanzetten in Docker Desktop, daarna in PowerShell `wsl --shutdown` en WSL opnieuw openen |
| `Cannot connect to the Docker daemon` | Docker Desktop draait nog niet; wachten tot **Engine running** |
| `port 5432 is already allocated` | er draait al een PostgreSQL op je pc; stop die of wijzig de poort in `compose.yaml` |
| `$'\r': command not found` | de repo staat in een Windows-map met Windows-regeleinden; clone in WSL |
| Tabellen ontbreken | `alembic upgrade head` draaien en de foutmelding lezen |
