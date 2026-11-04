# Migrations

Schemawijzigingen met Alembic. Elke wijziging aan een tabel gaat via een nieuwe migratie, nooit door een bestaande migratie aan te passen.

Migraties zijn in gewone SQL geschreven (`op.execute`), zodat ze één op één naast `../erd/ses-database.dbml` te lezen zijn. Er is geen autogenerate.

Commando's, vanuit de root van de repo in de dev container (`DATABASE_URL` staat al klaar):

| Commando | Wat het doet |
| --- | --- |
| `alembic -c database/alembic.ini upgrade head` | database bijwerken naar de nieuwste versie |
| `alembic -c database/alembic.ini current` | huidige versie tonen |
| `alembic -c database/alembic.ini downgrade -1` | laatste migratie terugdraaien |
| `alembic -c database/alembic.ini revision -m "add x to y"` | nieuwe lege migratie maken in `versions/` |
| `alembic -c database/alembic.ini upgrade head --sql` | de SQL tonen zonder uit te voeren |

Werkwijze bij een wijziging: eerst `../erd/ses-database.dbml` aanpassen, dan een nieuwe migratie schrijven die precies die wijziging doet.
