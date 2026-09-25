/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev-only fallback; in the image the backend renders the DSN into index.html. */
  readonly VITE_SENTRY_DSN?: string;
}
