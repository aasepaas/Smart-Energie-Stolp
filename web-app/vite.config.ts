/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The web app only talks to the Frontend API. In development Vite forwards /v1 to it,
// so the browser sees one origin (no CORS) and the refresh cookie path /v1/auth works.
// Inside the dev container the API is http://frontend-api:8002; override with
// FRONTEND_API_URL, for example http://localhost:8002 when running outside it.
const apiUrl = process.env.FRONTEND_API_URL ?? 'http://frontend-api:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/v1': { target: apiUrl, changeOrigin: true } },
  },
  preview: {
    port: 4173,
    proxy: { '/v1': { target: apiUrl, changeOrigin: true } },
  },
  test: {
    environment: 'node',
    env: { VITE_DEMO_EMAIL: 'demo@example.org', VITE_DEMO_PASSWORD: 'demo password 123' },
  },
})
