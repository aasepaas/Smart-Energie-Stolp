# ses-common

Gedeelde Python-package voor de backend-containers, zodat dezelfde code niet in elke service opnieuw geschreven wordt.

Geplande modules (`src/ses_common/`):

| Module | Inhoud |
| --- | --- |
| `backend_client.py` | client voor de Backend API (gebruikt door processing, training en forecast) |
| `db.py` | connection pool, gedeeld door beide API's |
| `schemas.py` | datamodellen (pydantic) |
| `config.py` | instellingen uit omgevingsvariabelen |
| `timeutils.py` | UTC en kwartieren |
