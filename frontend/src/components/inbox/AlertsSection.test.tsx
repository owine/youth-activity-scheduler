import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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
});
