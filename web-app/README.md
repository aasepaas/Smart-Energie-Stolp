# Web app

Container **Web app** (C4 view 3.1): single-page application in React and TypeScript. It only talks to the Frontend API.

## Current state: demo admin page

For now this is one admin page without a login form, roles or router:

- **Import meter data:** upload a CSV export, follow the import until it is done (`POST /v1/uploads`, `GET /v1/uploads/{id}`).
- **Simultaneity:** for a period of days, the simultaneity over the whole period, shared energy, feed-in and consumption, and a bar per day (`GET /v1/simultaneity?bucket=day`). The headline figure is the API's total (sum of shared energy / sum of feed-in), never an average of daily percentages. "Toon als tabel" shows the same numbers as a table.
- **Latest imports** (`GET /v1/uploads`).

After a successful import the period jumps to the period of that import. On start the page shows the period of the most recent import.

There is no login form yet. The API client logs in silently with a demo administrator account from `.env.local` and keeps the token in memory. Never use this outside local development: the password ends up in the JavaScript bundle.

## Structure

| Folder | C4 component | Now |
| --- | --- | --- |
| `src/app/` | User interface | `App.tsx` (the admin page), `app.css` (design tokens, light and dark) |
| `src/api/` | API client | `client.ts` (fetch wrapper, silent demo login), `types.ts` |
| `src/features/data-import/` | Data import | `UploadPanel.tsx`, `ImportHistory.tsx` |
| `src/features/data-view/` | Data view | `SimultaneityDashboard.tsx`, `SimultaneityChart.tsx` (Recharts) |
| `src/auth/` | Authentication | later: login form, refresh token, route guards |
| `src/features/settings/` | Settings | later |

All Dutch UI text is in `src/texts.ts`; code stays in English. Formatting and period helpers (Dutch local days ↔ UTC) are in `src/format.ts`.

## Running the demo (dev container)

The Frontend API, Backend API, Data processing service and database start with the dev container.

1. Create the demo administrator once:
   ```bash
   cd services/frontend-api
   python -m frontend_api.create_user admin@example.org      # asks for a password (at least 12 characters)
   ```
2. Fill in the account:
   ```bash
   cd web-app
   cp .env.example .env.local      # then fill in VITE_DEMO_PASSWORD
   ```
3. Start the web app and open `http://localhost:5173`:
   ```bash
   npm install      # only the first time (post-create.sh normally does this)
   npm run dev
   ```
4. Upload `database/seed/meter_data_4_weeks.csv`. Expected: 52,328 rows, 21 new meters, simultaneity 31.2 % over 16 March to 12 April 2026.

Vite forwards `/v1` to `http://frontend-api:8002`. Outside the dev container: `FRONTEND_API_URL=http://localhost:8002 npm run dev`.

## Commands

```bash
npm run dev       # development server with hot reload
npm test          # unit tests (Vitest)
npm run build     # type check and production build in dist/
```

## Later

A `Dockerfile` (static build behind nginx), the login form with refresh token, route guards per role, and the participant views.
