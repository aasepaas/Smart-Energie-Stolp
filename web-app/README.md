# Web app

Container **Web app**: single-page application voor deelnemers en beheerders, gebouwd met React en TypeScript.

Toont eigen verbruik, opwek, gelijktijdigheid, dynamische prijzen en adviezen. Beheerders uploaden hier ook CSV-meterdata en beheren instellingen. De app praat alleen met de Frontend API.

Geplande opbouw (`src/`), gelijk aan de componenten in het C4-model:

| Map | Component |
| --- | --- |
| `app/` | User interface: router, layout, route guards per rol |
| `auth/` | Authentication: login, JWT in geheugen, refresh |
| `features/data-view/` | Data view: grafieken, prijzen, adviezen |
| `features/data-import/` | Data import: uploadformulier en resultaat |
| `features/settings/` | Settings |
| `api/` | API client: fetch-wrapper met Bearer token |

Draait in productie als statische build achter nginx (`Dockerfile`).
