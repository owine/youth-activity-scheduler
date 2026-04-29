import { describe, it, expect } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { useCloseAlert, useReopenAlert } from './mutations';
import type { InboxSummary } from './types';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const seed = (overrides: Partial<InboxSummary['alerts'][number]> = {}) => ({
  id: 1,
  type: 'watchlist_hit' as const,
  kid_id: 1,
  kid_name: 'Sam',
  offering_id: null,
  site_id: null,
  channels: ['email'],
  scheduled_for: '2026-04-24T12:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'k',
  payload_json: {},
  summary_text: 'Watchlist hit for Sam',
  closed_at: null,
  close_reason: null,
  ...overrides,
});

const seedSummary = (alerts: ReturnType<typeof seed>[]): InboxSummary => ({
  window_start: '2026-04-17T00:00:00Z',
  window_end: '2026-04-24T00:00:00Z',
  alerts,
  new_matches_by_kid: [],
  site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
});

describe('useCloseAlert', () => {
  it('removes the alert from the open-only inbox cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData(['inbox', 'summary', 7, 'open-only'], seedSummary([seed()]));

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'acknowledged' });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only']);
    expect(after?.alerts).toEqual([]);
  });

  it('updates (does not remove) the alert in the with-closed inbox cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData(['inbox', 'summary', 7, 'with-closed'], seedSummary([seed()]));

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'dismissed' });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed']);
    expect(after?.alerts).toHaveLength(1);
    const alert = after!.alerts[0]!;
    expect(alert.close_reason).toBe('dismissed');
    expect(alert.closed_at).not.toBeNull();
  });

  it('rolls back on server error', async () => {
    server.use(
      http.post('/api/alerts/:id/close', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const openOnly = seedSummary([seed()]);
    const withClosed = seedSummary([seed()]);
    qc.setQueryData(['inbox', 'summary', 7, 'open-only'], openOnly);
    qc.setQueryData(['inbox', 'summary', 7, 'with-closed'], withClosed);

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'acknowledged' }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only'])?.alerts).toHaveLength(1);
    expect(qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only'])?.alerts[0]!.closed_at).toBeNull();
    expect(qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed'])?.alerts).toHaveLength(1);
    expect(qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed'])?.alerts[0]!.closed_at).toBeNull();
  });
});

describe('useReopenAlert', () => {
  it('clears closed_at and close_reason in cached row', async () => {
    const qc = new QueryClient();
    qc.setQueryData(
      ['inbox', 'summary', 7, 'with-closed'],
      seedSummary([seed({ closed_at: '2026-04-29T12:00:00Z', close_reason: 'acknowledged' })]),
    );

    const { result } = renderHook(() => useReopenAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1 });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed']);
    const reopened = after!.alerts[0]!;
    expect(reopened.closed_at).toBeNull();
    expect(reopened.close_reason).toBeNull();
  });
});
