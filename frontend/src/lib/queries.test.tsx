import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { server } from '@/test/server';
import { useInboxSummary } from './queries';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useInboxSummary', () => {
  it('returns summary on success', async () => {
    const { result } = renderHook(() => useInboxSummary(7), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.alerts).toEqual([]);
  });

  it('exposes error state on 500', async () => {
    server.use(
      http.get('/api/inbox/summary', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const { result } = renderHook(() => useInboxSummary(7), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
