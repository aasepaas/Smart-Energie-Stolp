# Init

SQL-scripts die PostgreSQL bij de eerste start uitvoert (in alfabetische volgorde):

- `01_extensions.sql`: TimescaleDB inschakelen;
- `02_roles.sql`: `frontend_role` en `backend_role`, met row-level security zodat de frontend alleen data van de ingelogde deelnemer ziet.
