import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { OutboxRow } from './OutboxRow';
import type { Alert } from '@/lib/types';

const makeAlert = (over: Partial<Alert> = {}): Alert => ({
  id: 1,
  type: 'watchlist_hit',
  kid_id: 1,
  offering_id: 10,
  site_id: 5,
  channels: ['email', 'ntfy'],
  scheduled_for: '2026-05-01T10:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'key-1',
  payload_json: {},
  closed_at: null,
  close_reason: null,
  summary_text: 'Cool activity found for Tayo',
  ...over,
});

function renderWithQueryClient(component: React.ReactNode, qc: QueryClient = new QueryClient()) {
  return render(<QueryClientProvider client={qc}>{component}</QueryClientProvider>);
}

describe('OutboxRow', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-05-01T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders type badge + summary_text + scheduled-for date', () => {
    const qc = new QueryClient();
    const alert = makeAlert({ scheduled_for: '2026-05-01T00:00:00Z' });
    renderWithQueryClient(<OutboxRow alert={alert} />, qc);

    // Badge with type
    expect(screen.getByText('watchlist_hit')).toBeInTheDocument();

    // Summary text
    expect(screen.getByText('Cool activity found for Tayo')).toBeInTheDocument();

    // Scheduled-for date (relDate should format to "Today" since current time is 2026-05-01 00:00:00Z)
    expect(screen.getByText(/Today/)).toBeInTheDocument();
  });

  it('shows correct status indicator based on alert state', () => {
    const qc = new QueryClient();

    // Test pending
    const { rerender } = renderWithQueryClient(
      <OutboxRow
        alert={makeAlert({
          sent_at: null,
          skipped: false,
          closed_at: null,
        })}
      />,
      qc,
    );
    expect(screen.getByText(/pending/)).toBeInTheDocument();

    // Test sent
    rerender(
      <QueryClientProvider client={qc}>
        <OutboxRow
          alert={makeAlert({
            sent_at: '2026-05-01T08:00:00Z',
            skipped: false,
            closed_at: null,
          })}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/sent/)).toBeInTheDocument();

    // Test skipped
    rerender(
      <QueryClientProvider client={qc}>
        <OutboxRow
          alert={makeAlert({
            sent_at: null,
            skipped: true,
            closed_at: null,
          })}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/skipped/)).toBeInTheDocument();

    // Test closed
    rerender(
      <QueryClientProvider client={qc}>
        <OutboxRow
          alert={makeAlert({
            sent_at: null,
            skipped: false,
            closed_at: '2026-04-30T20:00:00Z',
            close_reason: 'acknowledged',
          })}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/closed \(acknowledged\)/)).toBeInTheDocument();
  });

  it('renders channels list correctly', () => {
    const qc = new QueryClient();

    // Test with multiple channels
    const { rerender } = renderWithQueryClient(
      <OutboxRow
        alert={makeAlert({
          channels: ['email', 'ntfy'],
        })}
      />,
      qc,
    );
    expect(screen.getByText(/email, ntfy/)).toBeInTheDocument();

    // Test with empty channels
    rerender(
      <QueryClientProvider client={qc}>
        <OutboxRow
          alert={makeAlert({
            channels: [],
          })}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  it('fires useResendAlert mutation on Resend button click', async () => {
    const qc = new QueryClient();
    const alert = makeAlert({ id: 42 });

    let capturedUrl = '';
    server.use(
      http.post('/api/alerts/:id/resend', ({ params }) => {
        capturedUrl = `/api/alerts/${params.id}/resend`;
        return HttpResponse.json({
          id: 42,
          type: 'watchlist_hit',
          kid_id: 1,
          offering_id: 10,
          site_id: 5,
          channels: ['email', 'ntfy'],
          scheduled_for: '2026-05-01T10:00:00Z',
          sent_at: null,
          skipped: false,
          dedup_key: 'key-1',
          payload_json: {},
          closed_at: null,
          close_reason: null,
          summary_text: 'Cool activity found for Tayo',
        });
      }),
    );

    renderWithQueryClient(<OutboxRow alert={alert} />, qc);

    const resendButton = screen.getByRole('button', { name: /Resend/i });
    await userEvent.click(resendButton);

    await waitFor(() => {
      expect(capturedUrl).toBe('/api/alerts/42/resend');
    });
  });

  it('shows success pill on resend success', async () => {
    const qc = new QueryClient();
    const alert = makeAlert({ id: 42 });

    server.use(
      http.post('/api/alerts/:id/resend', () => {
        return HttpResponse.json({
          id: 42,
          type: 'watchlist_hit',
          kid_id: 1,
          offering_id: 10,
          site_id: 5,
          channels: ['email', 'ntfy'],
          scheduled_for: '2026-05-01T10:00:00Z',
          sent_at: null,
          skipped: false,
          dedup_key: 'key-1',
          payload_json: {},
          closed_at: null,
          close_reason: null,
          summary_text: 'Cool activity found for Tayo',
        });
      }),
    );

    renderWithQueryClient(<OutboxRow alert={alert} />, qc);

    const resendButton = screen.getByRole('button', { name: /Resend/i });
    await userEvent.click(resendButton);

    await waitFor(() => {
      expect(screen.getByText('Resend queued')).toBeInTheDocument();
    });
  });

  it('shows error pill on resend failure', async () => {
    const qc = new QueryClient();
    const alert = makeAlert({ id: 42 });

    server.use(
      http.post('/api/alerts/:id/resend', () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 });
      }),
    );

    renderWithQueryClient(<OutboxRow alert={alert} />, qc);

    const resendButton = screen.getByRole('button', { name: /Resend/i });
    await userEvent.click(resendButton);

    await waitFor(() => {
      expect(screen.getByText(/Failed:/)).toBeInTheDocument();
    });
  });
});
