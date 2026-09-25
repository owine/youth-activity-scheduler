import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Sentry from '@sentry/react';
import { initSentry, readSentryConfig, reportRouteError } from './sentry';

vi.mock('@sentry/react', () => ({
  init: vi.fn(),
  captureReactException: vi.fn(),
}));

const DSN = 'https://browserkey@glitchtip.example/2';

function docWithMeta(meta: Record<string, string>): Document {
  const doc = document.implementation.createHTMLDocument('t');
  for (const [name, content] of Object.entries(meta)) {
    const el = doc.createElement('meta');
    el.name = name;
    el.content = content;
    doc.head.appendChild(el);
  }
  return doc;
}

describe('readSentryConfig', () => {
  it('reads the DSN, release and environment the backend rendered', () => {
    const doc = docWithMeta({
      'sentry-browser-dsn': DSN,
      'sentry-release': 'abc123',
      'sentry-environment': 'staging',
    });
    expect(readSentryConfig(doc, undefined)).toEqual({
      dsn: DSN,
      release: 'abc123',
      environment: 'staging',
    });
  });

  it('falls back to VITE_SENTRY_DSN when the page has no meta (pnpm dev)', () => {
    expect(readSentryConfig(docWithMeta({}), DSN)).toEqual({ dsn: DSN });
  });

  it('prefers the runtime meta over the build-time fallback', () => {
    const doc = docWithMeta({ 'sentry-browser-dsn': DSN });
    expect(readSentryConfig(doc, 'https://other@glitchtip.example/9')?.dsn).toBe(DSN);
  });

  it('is null when there is no DSN anywhere', () => {
    expect(readSentryConfig(docWithMeta({}), undefined)).toBeNull();
    expect(readSentryConfig(docWithMeta({}), '')).toBeNull();
  });

  it('is null for a DSN that is not an http(s) URL', () => {
    expect(readSentryConfig(docWithMeta({}), 'not a url')).toBeNull();
    expect(readSentryConfig(docWithMeta({}), 'javascript:alert(1)')).toBeNull();
  });
});

describe('initSentry', () => {
  beforeEach(() => vi.mocked(Sentry.init).mockClear());
  afterEach(() => vi.mocked(Sentry.init).mockClear());

  it('does nothing without a config', () => {
    expect(initSentry(null)).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it('initialises errors-only: no tracing, no replay, no PII', () => {
    expect(initSentry({ dsn: DSN, release: 'abc123', environment: 'production' })).toBe(true);

    const options = vi.mocked(Sentry.init).mock.calls[0]![0]!;
    expect(options.dsn).toBe(DSN);
    expect(options.release).toBe('abc123');
    expect(options.environment).toBe('production');
    expect(options.sendDefaultPii).toBe(false);
    expect(options.tracesSampleRate).toBeUndefined();
    expect(options.tracePropagationTargets).toEqual([]);
    expect(options.replaysSessionSampleRate).toBeUndefined();
    expect(options.replaysOnErrorSampleRate).toBeUndefined();
    expect(options.integrations).toBeUndefined();
  });
});

describe('reportRouteError', () => {
  it('reports errors the router caught, with the React component stack', () => {
    const error = new Error('route render failed');
    const info = { componentStack: '\n    at KidPage' };
    reportRouteError(error, info);
    expect(Sentry.captureReactException).toHaveBeenCalledWith(error, info);
  });
});
