import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { Footer } from './Footer';

const server = setupServer();

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderFooter() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Footer />
    </QueryClientProvider>,
  );
}

describe('Footer', () => {
  it('renders version and short git sha as a commit link', async () => {
    server.use(
      http.get('/healthz', () =>
        HttpResponse.json({
          status: 'ok',
          git_sha: '6871d4e94bc681a4c0c0d7ff02b81eaf0801c572',
          version: '0.1.0',
        }),
      ),
    );
    renderFooter();
    expect(await screen.findByText(/YAS v0\.1\.0/)).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: '6871d4e' });
    expect(link).toHaveAttribute(
      'href',
      'https://github.com/owine/youth-activity-scheduler/commit/6871d4e94bc681a4c0c0d7ff02b81eaf0801c572',
    );
    expect(link).toHaveAttribute('title', '6871d4e94bc681a4c0c0d7ff02b81eaf0801c572');
  });

  it('renders only version when git_sha is unknown (local dev)', async () => {
    server.use(
      http.get('/healthz', () =>
        HttpResponse.json({ status: 'ok', git_sha: 'unknown', version: '0.1.0' }),
      ),
    );
    renderFooter();
    expect(await screen.findByText(/YAS v0\.1\.0/)).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders nothing while healthz is still loading', () => {
    server.use(
      http.get('/healthz', async () => {
        await new Promise(() => {}); // never resolves
        return HttpResponse.json({});
      }),
    );
    const { container } = renderFooter();
    expect(container).toBeEmptyDOMElement();
  });
});
