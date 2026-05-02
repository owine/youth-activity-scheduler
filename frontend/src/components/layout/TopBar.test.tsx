import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import {
  createRouter,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
} from '@tanstack/react-router';
import { AppShell } from './AppShell';

const server = setupServer(
  http.get('/api/kids', () =>
    HttpResponse.json([{ id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true }]),
  ),
  http.get('/api/inbox/summary', () =>
    HttpResponse.json({
      window_start: '2026-04-17T00:00:00Z',
      window_end: '2026-04-24T00:00:00Z',
      alerts: [
        {
          id: 1,
          type: 'watchlist_hit',
          kid_id: 1,
          kid_name: 'Sam',
          offering_id: null,
          site_id: null,
          channels: [],
          scheduled_for: '2026-04-24T00:00:00Z',
          sent_at: null,
          skipped: false,
          dedup_key: 'k',
          payload_json: {},
          summary_text: 'x',
        },
      ],
      new_matches_by_kid: [],
      site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
    }),
  ),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('TopBar', () => {
  it('renders kid switcher with active kids and alert badge with count', async () => {
    const root = createRootRoute({ component: () => <AppShell>{null}</AppShell> });
    const router = createRouter({
      routeTree: root,
      history: createMemoryHistory({ initialEntries: ['/'] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Sam')).toBeInTheDocument();
    expect(await screen.findByText('1')).toBeInTheDocument(); // alert badge
    expect(screen.getByRole('link', { name: 'Kids' })).toHaveAttribute('href', '/kids');
  });
});
