# Database

Container **Database**: PostgreSQL met TimescaleDB.

| Map | Inhoud |
| --- | --- |
| `init/` | SQL die bij de eerste start draait: extensies en rollen |
| `migrations/` | schemawijzigingen met Alembic |
| `seed/` | nepdata voor ontwikkeling en tests |

Tabellen: `readings`, `meter_links`, `participants`, `users`, `simultaneity`, `forecasts`, `advice`, `energy_prices`, `settings`, `import_log`.
