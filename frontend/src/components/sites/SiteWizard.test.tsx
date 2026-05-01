import { describe, it, expect, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { server } from '@/test/server';
import { SiteWizard } from './SiteWizard';

const navigateMock = vi.fn();
vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router');
  return { ...actual, useNavigate: () => navigateMock };
});

const makeWrapper =
  (qc: QueryClient) =>
  ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );

const makeQc = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

beforeEach(() => navigateMock.mockReset());

describe('SiteWizard', () => {
  it('renders name + base_url inputs and a disabled Discover button initially', () => {
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/base url/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /discover pages/i })).toBeDisabled();
  });

  it('enables Discover when name + base_url are valid', async () => {
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'TestSite');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://example.com');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /discover pages/i })).not.toBeDisabled(),
    );
  });

  it('Discover click POSTs /api/sites then /api/sites/:id/discover in sequence', async () => {
    let createdName: string | null = null;
    let discoverSiteId: string | null = null;
    server.use(
      http.post('/api/sites', async ({ request }) => {
        const b = (await request.json()) as { name: string; base_url: string };
        createdName = b.name;
        return HttpResponse.json(
          {
            id: 7,
            name: b.name,
            base_url: b.base_url,
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
      http.post('/api/sites/:id/discover', ({ params }) => {
        discoverSiteId = params.id as string;
        return HttpResponse.json({
          site_id: 7,
          seed_url: 'https://example.com',
          stats: {
            sitemap_urls: 0,
            link_urls: 1,
            filtered_junk: 0,
            fetched_heads: 1,
            classified: 1,
            returned: 1,
          },
          candidates: [
            {
              url: 'https://example.com/sched',
              title: 'Schedule',
              kind: 'html',
              score: 0.9,
              reason: 'top',
            },
          ],
        });
      }),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'TestSite');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://example.com');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await waitFor(() => expect(createdName).toBe('TestSite'));
    await waitFor(() => expect(discoverSiteId).toBe('7'));
    await screen.findByText(/Schedule/);
  });

  it('successful discover renders the candidate list with score >= 0.7 pre-checked', async () => {
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
          stats: {
            sitemap_urls: 0,
            link_urls: 0,
            filtered_junk: 0,
            fetched_heads: 0,
            classified: 0,
            returned: 0,
          },
          candidates: [
            { url: 'https://x/hi', title: 'Hi', kind: 'html', score: 0.9, reason: 'r' },
            { url: 'https://x/lo', title: 'Lo', kind: 'html', score: 0.4, reason: 'r' },
          ],
        }),
      ),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText(/Hi/);
    expect(screen.getByLabelText(/Hi/)).toBeChecked();
    expect(screen.queryByLabelText(/Lo/)).toBeNull(); // collapsed
  });

  it('PDF candidates are filtered out of the rendered list', async () => {
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
          stats: {
            sitemap_urls: 0,
            link_urls: 0,
            filtered_junk: 0,
            fetched_heads: 0,
            classified: 0,
            returned: 0,
          },
          candidates: [
            { url: 'https://x/pdf', title: 'PDF', kind: 'pdf', score: 0.95, reason: 'r' },
            { url: 'https://x/html', title: 'HTML', kind: 'html', score: 0.95, reason: 'r' },
          ],
        }),
      ),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText('HTML');
    expect(screen.queryByText('PDF')).toBeNull();
  });

  it('post-discover, name + base_url inputs are read-only with an "Edit URL" link that resets state', async () => {
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
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
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByRole('button', { name: /edit url/i });
    expect(screen.getByLabelText(/name/i)).toHaveAttribute('readonly');
    expect(screen.getByLabelText(/base url/i)).toHaveAttribute('readonly');
    await userEvent.click(screen.getByRole('button', { name: /edit url/i }));
    // Discover button should re-appear (state was reset)
    expect(screen.getByRole('button', { name: /discover pages/i })).toBeInTheDocument();
  });

  it('discover error renders ErrorBanner; manual entry remains usable', async () => {
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({ detail: 'llm_error' }, { status: 502 }),
      ),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText(/discovery failed/i);
    expect(screen.getByLabelText(/manual url/i)).toBeInTheDocument();
  });

  it('Save button disabled when 0 pages selected/added', async () => {
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
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
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText(/no candidates/i);
    expect(screen.getByRole('button', { name: /create site/i })).toBeDisabled();
  });

  it('Save click POSTs /pages per page with kind=schedule, then crawl-now, then navigates', async () => {
    const pageUrls: string[] = [];
    let crawled = false;
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
          stats: {
            sitemap_urls: 0,
            link_urls: 0,
            filtered_junk: 0,
            fetched_heads: 0,
            classified: 0,
            returned: 0,
          },
          candidates: [
            { url: 'https://x/sched', title: 'S', kind: 'html', score: 0.9, reason: 'r' },
          ],
        }),
      ),
      http.post('/api/sites/:id/pages', async ({ request }) => {
        const b = (await request.json()) as { url: string; kind: string };
        pageUrls.push(`${b.url}|${b.kind}`);
        return HttpResponse.json(
          {
            id: 1,
            url: b.url,
            kind: b.kind,
            content_hash: null,
            last_fetched: null,
            next_check_at: null,
          },
          { status: 201 },
        );
      }),
      http.post('/api/sites/:id/crawl-now', () => {
        crawled = true;
        return new HttpResponse(null, { status: 202 });
      }),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText(/^S$/);
    await userEvent.click(screen.getByRole('button', { name: /create site/i }));
    await waitFor(() => expect(pageUrls).toEqual(['https://x/sched|schedule']));
    await waitFor(() => expect(crawled).toBe(true));
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith({ to: '/sites/$id', params: { id: '7' } }),
    );
  });

  it('partial page-add failure keeps remaining selected and shows ErrorBanner', async () => {
    let calls = 0;
    server.use(
      http.post('/api/sites', () =>
        HttpResponse.json(
          {
            id: 7,
            name: 'X',
            base_url: 'https://x',
            adapter: 'llm',
            needs_browser: false,
            active: true,
            default_cadence_s: 21600,
            muted_until: null,
            pages: [],
          },
          { status: 201 },
        ),
      ),
      http.post('/api/sites/:id/discover', () =>
        HttpResponse.json({
          site_id: 7,
          seed_url: 'https://x',
          stats: {
            sitemap_urls: 0,
            link_urls: 0,
            filtered_junk: 0,
            fetched_heads: 0,
            classified: 0,
            returned: 0,
          },
          candidates: [
            { url: 'https://x/a', title: 'A', kind: 'html', score: 0.9, reason: 'r' },
            { url: 'https://x/b', title: 'B', kind: 'html', score: 0.85, reason: 'r' },
          ],
        }),
      ),
      http.post('/api/sites/:id/pages', async ({ request }) => {
        calls++;
        const b = (await request.json()) as { url: string };
        if (b.url.endsWith('/b')) {
          return HttpResponse.json({ detail: 'boom' }, { status: 500 });
        }
        return HttpResponse.json(
          {
            id: 1,
            url: b.url,
            kind: 'schedule',
            content_hash: null,
            last_fetched: null,
            next_check_at: null,
          },
          { status: 201 },
        );
      }),
    );
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'X');
    await userEvent.type(screen.getByLabelText(/base url/i), 'https://x');
    await userEvent.click(screen.getByRole('button', { name: /discover pages/i }));
    await screen.findByText(/^A$/);
    await userEvent.click(screen.getByRole('button', { name: /create site/i }));
    await screen.findByText(/added 1 of 2/i);
    // The succeeded URL is unchecked; the failed one is still checked
    expect(screen.getByLabelText(/https:\/\/x\/a/)).not.toBeChecked();
    expect(screen.getByLabelText(/https:\/\/x\/b/)).toBeChecked();
    expect(calls).toBe(2);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('clean cancel before discover navigates without ConfirmDialog', async () => {
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(navigateMock).toHaveBeenCalled();
  });

  it('dirty cancel before discover shows ConfirmDialog', async () => {
    render(<SiteWizard />, { wrapper: makeWrapper(makeQc()) });
    await userEvent.type(screen.getByLabelText(/name/i), 'dirty');
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
  });
});
