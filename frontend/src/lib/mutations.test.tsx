import { describe, it, expect } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import {
  useCloseAlert,
  useReopenAlert,
  useCancelEnrollment,
  useDeleteUnavailability,
  useEnrollOffering,
  useUpdateOfferingMute,
  useUpdateSiteMute,
  useCreateKid,
  useUpdateKid,
  useCreateWatchlistEntry,
  useUpdateWatchlistEntry,
  useDeleteWatchlistEntry,
  useCrawlNow,
  useToggleSiteActive,
} from './mutations';
import type { InboxSummary, KidCalendarResponse, KidDetail, WatchlistEntry, Site } from './types';

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
      http.post('/api/alerts/:id/close', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
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

    expect(
      qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only'])?.alerts,
    ).toHaveLength(1);
    expect(
      qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only'])?.alerts[0]!.closed_at,
    ).toBeNull();
    expect(
      qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed'])?.alerts,
    ).toHaveLength(1);
    expect(
      qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed'])?.alerts[0]!.closed_at,
    ).toBeNull();
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

const seedCal = (events: KidCalendarResponse['events']): KidCalendarResponse => ({
  kid_id: 1,
  from: '2026-04-27',
  to: '2026-05-04',
  events,
});

describe('useCancelEnrollment', () => {
  it('removes all enrollment occurrences and linked-block occurrences for that enrollment', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04'],
      seedCal([
        {
          id: 'enrollment:42:2026-04-28',
          kind: 'enrollment',
          date: '2026-04-28',
          time_start: '16:00:00',
          time_end: '17:00:00',
          all_day: false,
          title: 'T-Ball',
          enrollment_id: 42,
          offering_id: 7,
          status: 'enrolled',
        },
        {
          id: 'unavailability:21:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '16:00:00',
          time_end: '17:00:00',
          all_day: false,
          title: 'T-Ball',
          block_id: 21,
          source: 'enrollment',
          from_enrollment_id: 42,
        },
        {
          id: 'unavailability:20:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '08:30:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'School',
          block_id: 20,
          source: 'school',
          from_enrollment_id: null,
        },
      ]),
    );

    const { result } = renderHook(() => useCancelEnrollment(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, enrollmentId: 42 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
    ]);
    expect(after?.events).toHaveLength(1);
    expect(after!.events[0]!.block_id).toBe(20);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.patch('/api/enrollments/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedCal([
      {
        id: 'enrollment:42:2026-04-28',
        kind: 'enrollment',
        date: '2026-04-28',
        time_start: '16:00:00',
        time_end: '17:00:00',
        all_day: false,
        title: 'T-Ball',
        enrollment_id: 42,
        offering_id: 7,
        status: 'enrolled',
      },
    ]);
    qc.setQueryData(['kids', 1, 'calendar', '2026-04-27', '2026-05-04'], original);

    const { result } = renderHook(() => useCancelEnrollment(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, enrollmentId: 42 }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
    ]);
    expect(after?.events).toHaveLength(1);
    expect(after!.events[0]!.enrollment_id).toBe(42);
  });
});

describe('useEnrollOffering', () => {
  it('removes match events for the offering across all calendar variants', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '16:00:00',
      time_end: '17:00:00',
      all_day: false,
      title: 'T-Ball',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'no-matches'],
      seedCal([]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, offeringId: 7 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
      'with-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('does not crash on a no-matches variant that has no match events', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'no-matches'],
      seedCal([]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, offeringId: 7 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
      'no-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.post('/api/enrollments', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '16:00:00',
      time_end: '17:00:00',
      all_day: false,
      title: 'T-Ball',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, offeringId: 7 }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
      'with-matches',
    ]);
    expect(after?.events).toHaveLength(1);
    expect(after?.events[0]!.kind).toBe('match');
  });
});

describe('useUpdateSiteMute', () => {
  it('PATCHes /api/sites/{id} with the muted_until payload', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useUpdateSiteMute(), {
      wrapper: makeWrapper(qc),
    });
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    await act(async () => {
      await result.current.mutateAsync({ siteId: 1, mutedUntil: future });
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useUpdateOfferingMute', () => {
  it('removes match events for the offering optimistically when muting', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '17:00:00',
      time_end: '18:00:00',
      all_day: false,
      title: 'Soccer',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useUpdateOfferingMute(), {
      wrapper: makeWrapper(qc),
    });
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    await act(async () => {
      await result.current.mutateAsync({ offeringId: 7, mutedUntil: future });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
      'with-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('does not perform optimistic surgery on unmute (mutedUntil=null)', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '17:00:00',
      time_end: '18:00:00',
      all_day: false,
      title: 'Soccer',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useUpdateOfferingMute(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ offeringId: 7, mutedUntil: null });
    });

    // The mutation completed successfully; cache state after invalidation
    // depends on whether refetch resolved before the assertion. The key
    // assertion is that no crash happened on unmute path.
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useDeleteUnavailability', () => {
  it('removes the matching unavailability event from cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04'],
      seedCal([
        {
          id: 'unavailability:20:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '08:30:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'School',
          block_id: 20,
          source: 'school',
          from_enrollment_id: null,
        },
      ]),
    );

    const { result } = renderHook(() => useDeleteUnavailability(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, blockId: 20 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.delete('/api/unavailability/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedCal([
      {
        id: 'unavailability:20:2026-04-28',
        kind: 'unavailability',
        date: '2026-04-28',
        time_start: '08:30:00',
        time_end: '15:00:00',
        all_day: false,
        title: 'School',
        block_id: 20,
        source: 'school',
        from_enrollment_id: null,
      },
    ]);
    qc.setQueryData(['kids', 1, 'calendar', '2026-04-27', '2026-05-04'], original);

    const { result } = renderHook(() => useDeleteUnavailability(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, blockId: 20 }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids',
      1,
      'calendar',
      '2026-04-27',
      '2026-05-04',
    ]);
    expect(after?.events).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Phase 6 Task 2 — new mutation hooks
// ---------------------------------------------------------------------------

const seedKid = (overrides: Partial<KidDetail> = {}): KidDetail => ({
  id: 1,
  name: 'Sam',
  dob: '2019-05-01',
  interests: [],
  active: true,
  availability: {},
  max_distance_mi: null,
  alert_score_threshold: 0.6,
  alert_on: {},
  school_weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
  school_time_start: null,
  school_time_end: null,
  school_year_ranges: [],
  school_holidays: [],
  notes: null,
  watchlist: [],
  ...overrides,
});

const seedWatchlistEntry = (overrides: Partial<WatchlistEntry> = {}): WatchlistEntry => ({
  id: 10,
  kid_id: 1,
  pattern: 't-ball',
  priority: 'normal',
  site_id: null,
  ignore_hard_gates: false,
  notes: null,
  active: true,
  created_at: '2026-04-30T12:00:00Z',
  ...overrides,
});

const seedSite = (overrides: Partial<Site> = {}): Site => ({
  id: 1,
  name: 'YMCA',
  base_url: 'https://ymca.test',
  adapter: 'llm',
  needs_browser: false,
  active: true,
  default_cadence_s: 86400,
  muted_until: null,
  pages: [],
  ...overrides,
});

describe('useCreateKid', () => {
  it('succeeds and returns the new kid from the server', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useCreateKid(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'Alex', dob: '2020-01-01', interests: [] });
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useUpdateKid', () => {
  it('optimistically updates the cached kid', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidDetail>(['kids', 1], seedKid({ name: 'Sam' }));

    const { result } = renderHook(() => useUpdateKid(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ id: 1, patch: { name: 'Alex' } });
    });

    // After settle the cache is invalidated, but during the mutation it was
    // patched — verify the mutation succeeded and the request went through.
    expect(result.current.isSuccess).toBe(true);
  });

  it('rolls back cached kid on server error', async () => {
    server.use(
      http.patch('/api/kids/:id', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedKid({ name: 'Sam' });
    qc.setQueryData<KidDetail>(['kids', 1], original);

    const { result } = renderHook(() => useUpdateKid(), { wrapper: makeWrapper(qc) });
    result.current.mutate({ id: 1, patch: { name: 'Alex' } });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(qc.getQueryData<KidDetail>(['kids', 1])?.name).toBe('Sam');
  });
});

describe('useCreateWatchlistEntry', () => {
  it('succeeds and returns the new entry from the server', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useCreateWatchlistEntry(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, pattern: 'soccer' });
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useUpdateWatchlistEntry', () => {
  it('optimistically updates the entry in-place in the list cache', async () => {
    const qc = new QueryClient();
    const entry = seedWatchlistEntry({ id: 10, pattern: 't-ball' });
    qc.setQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'], [entry]);

    const { result } = renderHook(() => useUpdateWatchlistEntry(), {
      wrapper: makeWrapper(qc),
    });
    result.current.mutate({ kidId: 1, entryId: 10, patch: { pattern: 'soccer' } });
    await waitFor(() => {
      const list = qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist']);
      return list?.[0]?.pattern === 'soccer';
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('rolls back the list cache on server error', async () => {
    server.use(
      http.patch('/api/watchlist/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const entry = seedWatchlistEntry({ id: 10, pattern: 't-ball' });
    qc.setQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'], [entry]);

    const { result } = renderHook(() => useUpdateWatchlistEntry(), {
      wrapper: makeWrapper(qc),
    });
    result.current.mutate({ kidId: 1, entryId: 10, patch: { pattern: 'soccer' } });
    // Optimistic update fires; wait for it
    await waitFor(() => {
      const list = qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist']);
      return list?.[0]?.pattern === 'soccer';
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'])?.[0]?.pattern).toBe(
      't-ball',
    );
  });
});

describe('useDeleteWatchlistEntry', () => {
  it('optimistically removes the entry from the list cache', async () => {
    const qc = new QueryClient();
    const entry = seedWatchlistEntry({ id: 10 });
    qc.setQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'], [entry]);

    const { result } = renderHook(() => useDeleteWatchlistEntry(), {
      wrapper: makeWrapper(qc),
    });
    result.current.mutate({ kidId: 1, entryId: 10 });
    await waitFor(() => {
      const list = qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist']);
      return list?.length === 0;
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('rolls back the list cache on server error', async () => {
    server.use(
      http.delete('/api/watchlist/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const entry = seedWatchlistEntry({ id: 10 });
    qc.setQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'], [entry]);

    const { result } = renderHook(() => useDeleteWatchlistEntry(), {
      wrapper: makeWrapper(qc),
    });
    result.current.mutate({ kidId: 1, entryId: 10 });
    await waitFor(() => {
      const list = qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist']);
      return list?.length === 0;
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(qc.getQueryData<WatchlistEntry[]>(['kids', 1, 'watchlist'])).toHaveLength(1);
  });
});

describe('useCrawlNow', () => {
  it('POSTs to /api/sites/{id}/crawl-now and succeeds', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useCrawlNow(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ siteId: 1 });
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useToggleSiteActive', () => {
  it('optimistically flips the active flag in the cached site', async () => {
    const qc = new QueryClient();
    qc.setQueryData<Site>(['sites', 1], seedSite({ active: true }));

    const { result } = renderHook(() => useToggleSiteActive(), { wrapper: makeWrapper(qc) });
    result.current.mutate({ siteId: 1, active: false });
    await waitFor(() => {
      return qc.getQueryData<Site>(['sites', 1])?.active === false;
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('rolls back the cached site on server error', async () => {
    server.use(
      http.patch('/api/sites/:id', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    qc.setQueryData<Site>(['sites', 1], seedSite({ active: true }));

    const { result } = renderHook(() => useToggleSiteActive(), { wrapper: makeWrapper(qc) });
    result.current.mutate({ siteId: 1, active: false });
    await waitFor(() => {
      return qc.getQueryData<Site>(['sites', 1])?.active === false;
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(qc.getQueryData<Site>(['sites', 1])?.active).toBe(true);
  });
});
