/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Demo account the web app logs in with (no login form yet) */
  readonly VITE_DEMO_EMAIL?: string
  readonly VITE_DEMO_PASSWORD?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
