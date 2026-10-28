# Services

De backend-containers van SES, allemaal in Python. Elke map is een eigen Docker-container met een eigen `pyproject.toml`, `Dockerfile` en `tests/`.

| Map | Container | Rol |
| --- | --- | --- |
| `frontend-api/` | Frontend API | enige ingang voor de web app |
| `backend-api/` | Backend API | interne API tussen services en database |
| `processing-service/` | Data processing service | CSV importeren en gelijktijdigheid berekenen |
| `training-pipeline/` | Ingest and training pipeline | na elke export effect meten en hertrainen |
| `forecast-pipeline/` | Forecast pipeline | elke avond voorspellen en adviseren |

Gedeelde code (backend client, datamodellen, configuratie) staat in `packages/ses-common/`.
