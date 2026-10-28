# Backend API

Container **Backend API** (Python, Flask): interne API tussen de backend-services en de database.

Wordt aangeroepen door de Data processing service, de training pipeline en de forecast pipeline. Controleert per service een token en schrijft met de `backend_role` (onder andere upserts van meetwaarden op meter en UTC-tijdstempel).

Geplande opbouw (`src/backend_api/`): `endpoints/`, `authentication.py`, `query_builder.py`, `query_executor.py`.
