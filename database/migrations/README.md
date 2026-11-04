# Migrations

Schemawijzigingen met Alembic. Alembic houdt in de tabel `alembic_version` bij welke migraties al zijn uitgevoerd en voert alleen de nieuwe uit.

| Bestand | Inhoud |
| --- | --- |
| `../../alembic.ini` | waar de migraties staan (in de root, zodat `alembic` zonder opties werkt) |
| `env.py` | maakt verbinding met `DATABASE_URL` en voert de migraties uit |
| `versions/` | de migraties, in gewone SQL |

In de dev container draait `alembic upgrade head` vanzelf bij elke start. Handmatig, vanuit de root van de repo:

| Commando | Wat het doet |
| --- | --- |
| `alembic upgrade head` | database bijwerken naar de nieuwste migratie |
| `alembic current` | huidige versie tonen |
| `alembic downgrade -1` | laatste migratie terugdraaien |

## Nieuwe migratie

Kopieer de laatste migratie in `versions/` naar een nieuw bestand met het volgende nummer, bijvoorbeeld `0002_add_x_to_y.py`, en pas aan:

```python
"""Add x to y."""

from alembic import op

revision = "0002"
down_revision = "0001"   # nummer van de vorige migratie


def upgrade() -> None:
    op.execute("ALTER TABLE y ADD COLUMN x integer")


def downgrade() -> None:
    op.execute("ALTER TABLE y DROP COLUMN x")
```

Regels:

- pas eerst `../erd/ses-database.dbml` aan, en zet DBML en migratie in dezelfde PR;
- pas een migratie die al in `main` staat nooit meer aan, maak altijd een nieuwe;
- maken jullie tegelijk een migratie met hetzelfde `down_revision`, dan weigert Alembic met "multiple heads": hernummer er één.
