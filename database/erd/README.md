# ERD

| Bestand | Inhoud |
| --- | --- |
| `ses-database.dbml` | het databaseontwerp in DBML: tabellen, kolommen, relaties en toelichting |
| `ses-database.dbdiagram` | posities van de tabellen in het diagram, beheerd door de extensie |

Openen in VS Code met de dbdiagram-extensie.

## Relatie met de echte database

Er is **geen automatische sync** tussen de DBML en de database. De DBML is het ontwerp; de Alembic-migraties in `../migrations/` bepalen wat er echt in de database staat. Dat is bewust:

- DBML kent geen TimescaleDB-hypertables en de meeste CHECK-constraints, die staan alleen in de migraties;
- een database met data moet je wijzigen (`ALTER TABLE`), niet opnieuw opbouwen uit het ontwerp.

Wat wel automatisch gaat: bij elke **Rebuild Container** draait `alembic upgrade head`, zodat iedereen dezelfde migraties heeft.

## Werkwijze bij een wijziging

1. Pas `ses-database.dbml` aan.
2. Maak een nieuwe migratie:
   ```bash
   alembic -c database/alembic.ini revision -m "add column x to readings"
   ```
3. Schrijf in het nieuwe bestand in `../migrations/versions/` de SQL voor `upgrade()` en het terugdraaien in `downgrade()`.
4. Voer uit en controleer:
   ```bash
   alembic -c database/alembic.ini upgrade head
   psql -c '\d readings'
   ```
5. Zet de DBML-wijziging en de migratie in dezelfde commit en PR.

Pas een migratie die al in `main` staat nooit meer aan; maak altijd een nieuwe.

## Controleren of ontwerp en database overeenkomen

Genereer DBML uit de draaiende database en vergelijk die met het ontwerp (tabellen, kolommen, types en relaties; toelichting en hypertables ontbreken in de export):

```bash
npx -p @dbml/cli db2dbml postgres "$DATABASE_URL?schemas=public" -o /tmp/live.dbml
code --diff /tmp/live.dbml database/erd/ses-database.dbml
```
