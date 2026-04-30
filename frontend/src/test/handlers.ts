import { http, HttpResponse } from 'msw';

export const inboxSummaryFixture = {
  window_start: '2026-04-17T00:00:00Z',
  window_end: '2026-04-24T00:00:00Z',
  alerts: [],
  new_matches_by_kid: [],
  site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
};

export const handlers = [
  http.get('/api/kids', () => HttpResponse.json([])),
  http.get('/api/inbox/summary', () => HttpResponse.json(inboxSummaryFixture)),
  http.get('/api/sites', () => HttpResponse.json([])),
  http.get('/api/household', () =>
    HttpResponse.json({
      id: 1,
      home_location_id: null,
      home_address: null,
      home_location_name: null,
      default_max_distance_mi: null,
      digest_time: '07:00',
      quiet_hours_start: null,
      quiet_hours_end: null,
      daily_llm_cost_cap_usd: 1.0,
    }),
  ),
  http.get('/api/alert_routing', () => HttpResponse.json([])),
  http.post('/api/alerts/:id/close', async ({ request, params }) => {
    const body = (await request.json()) as { reason: 'acknowledged' | 'dismissed' };
    return HttpResponse.json({
      id: Number(params.id),
      type: 'watchlist_hit',
      kid_id: 1,
      offering_id: null,
      site_id: null,
      channels: ['email'],
      scheduled_for: '2026-04-24T12:00:00Z',
      sent_at: null,
      skipped: false,
      dedup_key: 'k',
      payload_json: {},
      closed_at: '2026-04-29T12:00:00Z',
      close_reason: body.reason,
    });
  }),
  http.post('/api/alerts/:id/reopen', ({ params }) => {
    return HttpResponse.json({
      id: Number(params.id),
      type: 'watchlist_hit',
      kid_id: 1,
      offering_id: null,
      site_id: null,
      channels: ['email'],
      scheduled_for: '2026-04-24T12:00:00Z',
      sent_at: null,
      skipped: false,
      dedup_key: 'k',
      payload_json: {},
      closed_at: null,
      close_reason: null,
    });
  }),
  http.get('/api/kids/:id/calendar', ({ params, request }) => {
    const url = new URL(request.url);
    const includeMatches = url.searchParams.get('include_matches') === 'true';
    const events = includeMatches
      ? [
          {
            id: 'match:99:2026-04-29',
            kind: 'match',
            date: '2026-04-29',
            time_start: '17:00:00',
            time_end: '18:00:00',
            all_day: false,
            title: 'Soccer',
            offering_id: 99,
            score: 0.85,
            registration_url: 'https://example.com/soccer',
          },
        ]
      : [];
    return HttpResponse.json({
      kid_id: Number(params.id),
      from: url.searchParams.get('from'),
      to: url.searchParams.get('to'),
      events,
    });
  }),
  http.patch('/api/enrollments/:id', async ({ params, request }) => {
    const body = (await request.json()) as { status?: string };
    return HttpResponse.json({
      id: Number(params.id),
      kid_id: 1,
      offering_id: 1,
      status: body.status ?? 'cancelled',
      enrolled_at: null,
      notes: null,
      created_at: '2026-04-29T12:00:00Z',
    });
  }),
  http.delete('/api/unavailability/:id', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/enrollments', async ({ request }) => {
    const body = (await request.json()) as { kid_id: number; offering_id: number; status: string };
    return HttpResponse.json({
      id: 999,
      kid_id: body.kid_id,
      offering_id: body.offering_id,
      status: body.status,
      enrolled_at: '2026-04-29T12:00:00Z',
      notes: null,
      created_at: '2026-04-29T12:00:00Z',
    }, { status: 201 });
  }),
];
