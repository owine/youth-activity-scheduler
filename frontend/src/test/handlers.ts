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
  http.get('/api/matches', () => HttpResponse.json([])),
  http.get('/api/enrollments', () => HttpResponse.json([])),
  http.get('/api/inbox/summary', () => HttpResponse.json(inboxSummaryFixture)),
  http.get('/api/sites', () => HttpResponse.json([])),
  http.get('/api/household', () =>
    HttpResponse.json({
      id: 1,
      home_location_id: null,
      home_address: null,
      home_location_name: null,
      home_lat: null,
      home_lon: null,
      default_max_distance_mi: null,
      digest_time: '07:00',
      quiet_hours_start: null,
      quiet_hours_end: null,
      daily_llm_cost_cap_usd: 1.0,
      email_configured: false,
      ntfy_configured: false,
      pushover_configured: false,
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
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: Number(params.id),
      kid_id: 1,
      offering_id: 1,
      status: body.status ?? 'interested',
      enrolled_at: body.enrolled_at ?? null,
      notes: body.notes ?? null,
      created_at: '2026-04-29T12:00:00Z',
      offering: {
        id: 1,
        name: 'X',
        program_type: 'soccer',
        age_min: null,
        age_max: null,
        start_date: null,
        end_date: null,
        days_of_week: [],
        time_start: null,
        time_end: null,
        price_cents: null,
        registration_url: null,
        site_id: 1,
        registration_opens_at: null,
        site_name: 'S',
        muted_until: null,
        location_lat: null,
        location_lon: null,
      },
    });
  }),
  http.delete('/api/unavailability/:id', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/enrollments', async ({ request }) => {
    const body = (await request.json()) as { kid_id: number; offering_id: number; status: string };
    return HttpResponse.json(
      {
        id: 999,
        kid_id: body.kid_id,
        offering_id: body.offering_id,
        status: body.status,
        enrolled_at: '2026-04-29T12:00:00Z',
        notes: null,
        created_at: '2026-04-29T12:00:00Z',
      },
      { status: 201 },
    );
  }),
  http.patch('/api/sites/:id', async ({ params, request }) => {
    const body = (await request.json()) as { muted_until?: string | null };
    return HttpResponse.json({
      id: Number(params.id),
      name: 'X',
      base_url: 'https://x',
      adapter: 'llm',
      needs_browser: false,
      active: true,
      default_cadence_s: 86400,
      muted_until: body.muted_until ?? null,
      pages: [],
    });
  }),
  http.patch('/api/offerings/:id', async ({ params, request }) => {
    const body = (await request.json()) as { muted_until?: string | null };
    return HttpResponse.json({
      id: Number(params.id),
      name: 'T-Ball',
      site_id: 1,
      muted_until: body.muted_until ?? null,
    });
  }),
  http.post('/api/kids', async ({ request }) => {
    const body = (await request.json()) as { name: string; dob: string };
    return HttpResponse.json(
      {
        id: 999,
        name: body.name,
        dob: body.dob,
        interests: [],
        school_weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
        school_time_start: null,
        school_time_end: null,
        school_year_ranges: [],
        school_holidays: [],
        max_distance_mi: null,
        alert_score_threshold: 0.6,
        alert_on: {},
        notes: null,
        active: true,
        created_at: '2026-04-30T12:00:00Z',
      },
      { status: 201 },
    );
  }),
  http.patch('/api/kids/:id', async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: Number(params.id),
      name: 'Sam',
      dob: '2019-05-01',
      interests: [],
      school_weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
      school_time_start: null,
      school_time_end: null,
      school_year_ranges: [],
      school_holidays: [],
      max_distance_mi: null,
      alert_score_threshold: 0.6,
      alert_on: {},
      notes: null,
      active: true,
      created_at: '2026-04-30T12:00:00Z',
      ...body,
    });
  }),
  http.post('/api/kids/:kid_id/watchlist', async ({ params, request }) => {
    const body = (await request.json()) as { pattern: string; priority?: string };
    return HttpResponse.json(
      {
        id: 888,
        kid_id: Number(params.kid_id),
        pattern: body.pattern,
        priority: body.priority ?? 'normal',
        site_id: null,
        ignore_hard_gates: false,
        notes: null,
        active: true,
        created_at: '2026-04-30T12:00:00Z',
      },
      { status: 201 },
    );
  }),
  http.patch('/api/watchlist/:id', async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: Number(params.id),
      kid_id: 1,
      pattern: 't-ball',
      priority: 'normal',
      site_id: null,
      ignore_hard_gates: false,
      notes: null,
      active: true,
      created_at: '2026-04-30T12:00:00Z',
      ...body,
    });
  }),
  http.delete('/api/watchlist/:id', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/sites/:id/crawl-now', () => new HttpResponse(null, { status: 202 })),
  http.get('/api/sites/:id', ({ params }) =>
    HttpResponse.json({
      id: Number(params.id),
      name: 'X',
      base_url: 'https://x',
      adapter: 'llm',
      needs_browser: false,
      active: true,
      default_cadence_s: 86400,
      muted_until: null,
      pages: [],
    }),
  ),
  http.get('/api/sites/:id/crawls', () => HttpResponse.json([])),
  http.post('/api/sites', async ({ request }) => {
    const body = (await request.json()) as { name: string; base_url: string };
    return HttpResponse.json(
      {
        id: 99,
        name: body.name,
        base_url: body.base_url,
        adapter: 'llm',
        needs_browser: false,
        active: true,
        default_cadence_s: 21600,
        muted_until: null,
        pages: [],
      },
      { status: 201 },
    );
  }),
  http.post('/api/sites/:id/discover', () =>
    HttpResponse.json({
      site_id: 99,
      seed_url: 'https://example.com',
      stats: {
        sitemap_urls: 0,
        link_urls: 0,
        filtered_junk: 0,
        fetched_heads: 0,
        classified: 0,
        returned: 0,
      },
      candidates: [],
    }),
  ),
  http.post('/api/sites/:id/pages', async ({ request }) => {
    const body = (await request.json()) as { url: string; kind: string };
    return HttpResponse.json(
      {
        id: 999,
        url: body.url,
        kind: body.kind,
        content_hash: null,
        last_fetched: null,
        next_check_at: null,
      },
      { status: 201 },
    );
  }),
  http.patch('/api/household', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: 1,
      home_location_id: null,
      home_address: null,
      home_location_name: null,
      home_lat: null,
      home_lon: null,
      default_max_distance_mi: null,
      digest_time: '07:00',
      quiet_hours_start: null,
      quiet_hours_end: null,
      daily_llm_cost_cap_usd: 1.0,
      email_configured: false,
      ntfy_configured: false,
      pushover_configured: false,
      ...body,
    });
  }),
  http.patch('/api/alert_routing/:type', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      type: 'new_match',
      channels: body.channels ?? [],
      enabled: body.enabled !== undefined ? body.enabled : true,
    });
  }),
  http.post('/api/notifiers/:channel/test', () => HttpResponse.json({ ok: true, detail: 'sent' })),
  // GET /api/alerts — default empty list
  http.get('/api/alerts', () => HttpResponse.json({ items: [], total: 0, limit: 25, offset: 0 })),
  // POST /api/alerts/:id/resend — clones the alert
  http.post('/api/alerts/:id/resend', ({ params }) =>
    HttpResponse.json(
      {
        id: 999,
        type: 'new_match',
        kid_id: 1,
        offering_id: null,
        site_id: null,
        channels: ['email'],
        scheduled_for: '2026-05-01T00:00:00Z',
        sent_at: null,
        skipped: false,
        dedup_key: `clone:${params.id}`,
        payload_json: {},
        closed_at: null,
        close_reason: null,
        summary_text: 'Resent alert',
      },
      { status: 202 },
    ),
  ),
  // GET /api/digest/preview — default minimal render
  http.get('/api/digest/preview', () =>
    HttpResponse.json({
      subject: 'Daily digest — preview',
      body_plain: 'Preview body',
      body_html: '<p>Preview body</p>',
    }),
  ),
];
