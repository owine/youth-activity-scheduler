import * as Sentry from '@sentry/react';
import type { ErrorInfo } from 'react';

export interface SentryConfig {
  dsn: string;
  release?: string;
  environment?: string;
}

function meta(doc: Document, name: string): string | undefined {
  const content = doc.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content.trim();
  return content || undefined;
}

function isHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Browser Sentry config, or null when reporting is off.
 *
 * The backend renders the DSN into index.html at request time (see
 * yas/web/spa_fallback.py), so one published image serves any deployment and
 * no DSN is inlined into the bundle. VITE_SENTRY_DSN is only a fallback for
 * `pnpm dev`, where Vite serves its own index.html.
 */
export function readSentryConfig(
  doc: Document = document,
  devDsn: string | undefined = import.meta.env.VITE_SENTRY_DSN,
): SentryConfig | null {
  const dsn = meta(doc, 'sentry-browser-dsn') ?? devDsn?.trim();
  if (!dsn || !isHttpUrl(dsn)) return null;
  const config: SentryConfig = { dsn };
  const release = meta(doc, 'sentry-release');
  const environment = meta(doc, 'sentry-environment');
  if (release) config.release = release;
  if (environment) config.environment = environment;
  return config;
}

/** Errors only: no tracing or replay integrations (GlitchTip has no replay). */
export function initSentry(config: SentryConfig | null = readSentryConfig()): boolean {
  if (!config) return false;
  Sentry.init({
    ...config,
    sendDefaultPii: false,
    // Tracing is off (no browserTracingIntegration, no tracesSampleRate), so
    // no trace headers go out anyway; pinned empty so adding tracing later
    // can't start sending them to the API by default.
    tracePropagationTargets: [],
  });
  return true;
}

/**
 * Router `defaultOnCatch`. TanStack Router wraps every route match in its own
 * CatchBoundary, so errors thrown while rendering a route never reach the
 * app-level ErrorBoundary — they have to be reported from here.
 */
export function reportRouteError(error: unknown, errorInfo: ErrorInfo): void {
  Sentry.captureReactException(error, errorInfo);
}
