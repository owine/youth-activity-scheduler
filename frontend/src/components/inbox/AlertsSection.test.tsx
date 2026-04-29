import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsSection } from './AlertsSection';

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const alerts = [
  {
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
  },
];

const closedAlerts = [
  {
    id: 2,
    type: 'waitlist_opened',
    kid_id: 2,
    kid_name: 'Alex',
    offering_id: null,
    site_id: null,
    channels: ['email'],
    scheduled_for: '2026-04-20T12:00:00Z',
    sent_at: null,
    skipped: false,
    dedup_key: 'k2',
    payload_json: {},
    summary_text: 'Waitlist opened for Alex',
    closed_at: '2026-04-21T10:00:00Z',
    close_reason: 'resolved',
  },
];

describe('AlertsSection', () => {
  it('renders empty state', () => {
    wrap(<AlertsSection alerts={[]} />);
    expect(screen.getByText(/no alerts this week/i)).toBeInTheDocument();
  });

  it('renders rows and opens drawer on click', () => {
    wrap(<AlertsSection alerts={alerts as never} />);
    fireEvent.click(screen.getByText('Watchlist hit for Sam'));
    // Drawer renders the summary text
    expect(screen.getAllByText('Watchlist hit for Sam').length).toBeGreaterThan(0);
  });

  it('calls onIncludeClosedChange with true when Show closed is toggled on', async () => {
    const handler = vi.fn();
    wrap(<AlertsSection alerts={alerts as never} onIncludeClosedChange={handler} />);
    await userEvent.click(screen.getByLabelText(/show closed/i));
    expect(handler).toHaveBeenCalledWith(true);
  });

  it('renders Closed pill for alerts with closed_at set', () => {
    wrap(<AlertsSection alerts={closedAlerts as never} />);
    expect(screen.getByText(/^closed$/i)).toBeInTheDocument();
  });
});
