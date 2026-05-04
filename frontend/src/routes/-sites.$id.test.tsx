import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { createRouter, createMemoryHistory, RouterProvider } from '@tanstack/react-router';
import { server } from '@/test/server';
import { routeTree } from '@/routeTree.gen';

const siteFixture = {
  id: 1,
  name: 'Test Site',
  base_url: 'https://example.com',
  adapter: 'llm',
  needs_browser: false,
  active: true,
  default_cadence_s: 86400,
  muted_until: null,
  pages: [],
};

describe('SiteDetailPage', () => {
  afterEach(() => {
    server.resetHandlers();
  });

  const renderWithRouter = (siteId: number = 1) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createRouter({
      routeTree,
      history: createMemoryHistory({ initialEntries: [`/sites/${siteId}`] }),
    });
    return render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  };

  it('"Crawl now" button fires useCrawlNow mutation', async () => {
    let crawlNowCalled = false;

    server.use(
      http.get('/api/sites/1', () => HttpResponse.json(siteFixture)),
      http.get('/api/sites/1/crawls', () => HttpResponse.json([])),
      http.post('/api/sites/1/crawl-now', () => {
        crawlNowCalled = true;
        return new HttpResponse(null, { status: 202 });
      }),
    );

    const user = userEvent.setup({ delay: null });
    renderWithRouter(1);

    // Wait for site name to appear (confirms data loaded)
    const heading = await screen.findByText('Test Site', {}, { timeout: 5000 });
    expect(heading).toBeInTheDocument();

    const crawlButton = screen.getByRole('button', { name: /crawl now/i });
    await user.click(crawlButton);

    // Verify mutation was called
    await waitFor(() => {
      expect(crawlNowCalled).toBe(true);
    });

    // Verify "Queued ✓" label appears briefly
    expect(await screen.findByText(/Queued ✓/i, {}, { timeout: 3000 })).toBeInTheDocument();

    // Wait a bit for the label to disappear due to the 2000ms timeout
    await new Promise((resolve) => setTimeout(resolve, 2100));

    expect(screen.queryByText(/Queued ✓/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /crawl now/i })).toBeInTheDocument();
  });

  it('"Pause" button fires useToggleSiteActive mutation', async () => {
    let patchCalled = false;
    let patchBody: { active?: boolean } | undefined;

    server.use(
      http.get('/api/sites/1', () => HttpResponse.json(siteFixture)),
      http.get('/api/sites/1/crawls', () => HttpResponse.json([])),
      http.patch('/api/sites/1', async ({ request }) => {
        patchCalled = true;
        patchBody = (await request.json()) as { active?: boolean };
        return HttpResponse.json({
          ...siteFixture,
          active: patchBody.active !== undefined ? patchBody.active : siteFixture.active,
        });
      }),
    );

    const user = userEvent.setup({ delay: null });
    renderWithRouter(1);

    // Wait for site name to appear (confirms data loaded)
    await screen.findByText('Test Site', {}, { timeout: 5000 });

    // Site starts active, so button should say "Pause"
    const pauseButton = screen.getByRole('button', { name: /pause/i });
    expect(pauseButton).toBeInTheDocument();

    await user.click(pauseButton);

    // Verify mutation was called with active: false
    await waitFor(() => {
      expect(patchCalled).toBe(true);
    });
    expect(patchBody?.active).toBe(false);
  });

  it('"Resume" button shows when site is paused', async () => {
    const inactiveSite = { ...siteFixture, active: false };

    server.use(
      http.get('/api/sites/1', () => HttpResponse.json(inactiveSite)),
      http.get('/api/sites/1/crawls', () => HttpResponse.json([])),
    );

    renderWithRouter(1);

    // When inactive, button should say "Resume", not "Pause"
    expect(
      await screen.findByRole('button', { name: /resume/i }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /pause/i })).not.toBeInTheDocument();
  });

  it('displays "Paused" pill when site is inactive', async () => {
    const inactiveSite = { ...siteFixture, active: false };

    server.use(
      http.get('/api/sites/1', () => HttpResponse.json(inactiveSite)),
      http.get('/api/sites/1/crawls', () => HttpResponse.json([])),
    );

    renderWithRouter(1);

    expect(await screen.findByText('Paused', {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it('does not display "Paused" pill when site is active', async () => {
    server.use(
      http.get('/api/sites/1', () => HttpResponse.json(siteFixture)),
      http.get('/api/sites/1/crawls', () => HttpResponse.json([])),
    );

    renderWithRouter(1);

    await screen.findByText('Test Site', {}, { timeout: 5000 });

    expect(screen.queryByText('Paused')).not.toBeInTheDocument();
  });
});
