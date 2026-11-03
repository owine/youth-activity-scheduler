import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { server } from '@/test/server';
import { useAlerts, useInboxSummary } from './queries';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useInboxSummary', () => {
  it('returns summary on success', async () => {
    const { result } = renderHook(() => useInboxSummary({ days: 7 }), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.alerts).toEqual([]);
  });

  it('exposes error state on 500', async () => {
    server.use(
      http.get('/api/inbox/summary', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const { result } = renderHook(() => useInboxSummary({ days: 7 }), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useAlerts', () => {
  it('sends an Until date as the end of that day so the day is included', async () => {
    let params: URLSearchParams | null = null;
    server.use(
      http.get('/api/alerts', ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json({ items: [], total: 0, limit: 25, offset: 0 });
      }),
    );
    const filters = {
      kidId: null,
      type: null,
      status: null,
      since: '2026-11-01',
      until: '2026-11-02',
      page: 0,
    };
    const { result } = renderHook(() => useAlerts(filters), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(params!.get('since')).toBe('2026-11-01');
    expect(params!.get('until')).toBe('2026-11-02T23:59:59.999999');
  });
});
