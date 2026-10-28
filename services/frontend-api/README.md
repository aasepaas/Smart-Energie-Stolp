# Frontend API

Container **Frontend API** (Python, Flask): de enige ingang voor de web app.

- controleert de JWT, de rol en of de gebruiker de gevraagde data mag zien;
- beantwoordt queries rechtstreeks uit de database met de `frontend_role`;
- stuurt CSV-uploads door naar de Data processing service (`POST /imports`).

Geplande opbouw (`src/frontend_api/`): `app.py` (create_app), `endpoints/` (blueprints voor auth, readings, simultaneity, prices, advice, uploads, settings), `authentication.py`, `query_builder.py`, `query_executor.py`, `upload_handler.py`.
