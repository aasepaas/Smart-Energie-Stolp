# Database

Container **Database**: PostgreSQL met TimescaleDB.

| Map | Inhoud |
| --- | --- |
| `init/` | SQL die bij de eerste start draait: extensies en rollen |
| `migrations/` | schemawijzigingen met Alembic |
| `seed/` | nepdata voor ontwikkeling en tests |

Het ontwerp staat in `erd/ses-database.dbml` (open met de dbdiagram-extensie). Het schema zelf wordt aangemaakt met de Alembic-migraties in `migrations/`.

Tabellen: `participants`, `users`, `participant_appliances`, `settings`, `import_log`, `meters`, `readings`, `community_simultaneity`, `forecasts`, `energy_prices`, `advice`.

Hypertables (TimescaleDB): `readings`, `community_simultaneity`, `forecasts`, `energy_prices`.
