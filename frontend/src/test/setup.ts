import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, expect } from 'vitest';
import { notifyManager } from '@tanstack/query-core';
import { isCommonAssetRequest } from 'msw';
import { HttpNetworkFrame } from 'msw/experimental';
import { server } from './server';

// React Query uses setTimeout(fn, 0) by default, which `act()` may not fully
// drain in JSDOM. Switch to queueMicrotask so state updates flush synchronously
// within act() wrappers in tests.
notifyManager.setScheduler(queueMicrotask);

// Node 22+ ships a built-in localStorage backed by --localstorage-file.
// When no file path is configured the global is present but broken
// (getItem / setItem / etc. are not functions).  Replace it with a minimal
// in-memory implementation so tests that exercise localStorage-dependent
// code (e.g. ThemeToggle → getStoredTheme) work correctly.
if (typeof localStorage === 'undefined' || typeof localStorage.getItem !== 'function') {
  const store: Record<string, string> = {};
  const mockStorage: Storage = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      Object.keys(store).forEach((k) => delete store[k]);
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
    get length() {
      return Object.keys(store).length;
    },
  };
  Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true });
}

// Fail any test that makes a request no handler covers. The built-in 'error'
// strategy only console.errors and rejects that one fetch, which a component's
// error state can swallow, so the test still passes. Record each one instead
// and fail the test in afterEach. Throwing makes MSW answer the fetch with a
// 500 rather than pass it through, so nothing reaches the real network.
const unhandled: string[] = [];

beforeAll(() =>
  server.listen({
    onUnhandledFrame({ frame }) {
      if (frame instanceof HttpNetworkFrame) {
        const { request } = frame.data;
        // Mirrors the predefined strategies, which ignore common static assets.
        if (isCommonAssetRequest(request)) return;
        unhandled.push(`${request.method} ${request.url}`);
      } else {
        unhandled.push(`${frame.protocol} frame`);
      }
      throw new Error(`[MSW] No handler for ${unhandled.at(-1)}`);
    },
  }),
);
afterEach(() => {
  server.resetHandlers();
  const leaked = unhandled.splice(0);
  expect(leaked, `requests with no MSW handler:\n  ${leaked.join('\n  ')}`).toEqual([]);
});
afterAll(() => server.close());
