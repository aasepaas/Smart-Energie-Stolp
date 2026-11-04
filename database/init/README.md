# Init

SQL-scripts die PostgreSQL bij de eerste start uitvoert (in alfabetische volgorde):

- `01_extensions.sql`: TimescaleDB inschakelen.

Rollen en rechten staan niet hier maar in de Alembic-migraties (`../migrations/`), zodat ze met de tabellen meegaan.
