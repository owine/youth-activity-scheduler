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
];
