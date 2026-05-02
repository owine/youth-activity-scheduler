import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import type { InboxAlert } from '@/lib/types';

const openAlert: InboxAlert = {
  id: 1,
  type: 'watchlist_hit',
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
};

const closedAlert: InboxAlert = {
  ...openAlert,
  closed_at: '2026-04-29T11:00:00Z',
  close_reason: 'dismissed',
};

function renderDrawer(alert: InboxAlert | null, onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AlertDetailDrawer alert={alert} open={alert !== null} onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
}

describe('AlertDetailDrawer', () => {
  it('renders Acknowledge and Dismiss for an open alert', () => {
    renderDrawer(openAlert);
    expect(screen.getByRole('button', { name: /acknowledge/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reopen/i })).not.toBeInTheDocument();
  });

  it('renders Reopen for a closed alert', () => {
    renderDrawer(closedAlert);
    expect(screen.getByRole('button', { name: /reopen/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /acknowledge/i })).not.toBeInTheDocument();
  });

  it('closes the drawer after a successful close mutation', async () => {
    const onOpenChange = vi.fn();
    renderDrawer(openAlert, onOpenChange);
    await userEvent.click(screen.getByRole('button', { name: /acknowledge/i }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('shows an inline error banner if the mutation fails', async () => {
    server.use(
      http.post('/api/alerts/:id/close', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderDrawer(openAlert);
    await userEvent.click(screen.getByRole('button', { name: /acknowledge/i }));
    await waitFor(() =>
      expect(screen.getAllByText(/couldn't load|error|failed/i).length).toBeGreaterThan(0),
    );
    // Buttons re-enabled after error.
    expect(screen.getByRole('button', { name: /acknowledge/i })).not.toBeDisabled();
  });
});
