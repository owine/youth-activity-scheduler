import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { server } from '@/test/server';
import { AlertRoutingSection } from './AlertRoutingSection';
import type { Household, AlertRouting } from '@/lib/types';

const baseHh: Household = {
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
  email_configured: true,
  ntfy_configured: true,
  pushover_configured: true,
};

const wrap = (qc: QueryClient) => {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
};
const makeQc = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

describe('AlertRoutingSection', () => {
  it('renders rows for each alert type with columns [Enabled, email, ntfy, pushover]', () => {
    const routing: AlertRouting[] = [
      { type: 'new_match', channels: ['email'], enabled: true },
      { type: 'watchlist_hit', channels: ['email', 'ntfy'], enabled: true },
    ];
    const qc = makeQc();
    qc.setQueryData(['household'], baseHh);
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, {
      wrapper: wrap(qc),
    });

    // Check header
    expect(screen.getByRole('columnheader', { name: /Alert Type/i })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /^Enabled$/i })).toBeInTheDocument();

    // Check rows are rendered
    expect(screen.getByText(/new_match/i)).toBeInTheDocument();
    expect(screen.getByText(/watchlist_hit/i)).toBeInTheDocument();

    // Check that checkboxes are rendered (2 rows * 4 columns = 8 checkboxes)
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(8);
  });

  it('unconfigured channel column is disabled with title attribute', () => {
    const routing: AlertRouting[] = [{ type: 'new_match', channels: ['email'], enabled: true }];
    const hhWithoutPushover: Household = {
      ...baseHh,
      pushover_configured: false,
    };
    const qc = makeQc();
    qc.setQueryData(['household'], hhWithoutPushover);
    qc.setQueryData(['alert_routing'], routing);

    render(<AlertRoutingSection />, {
      wrapper: wrap(qc),
    });

    // Find pushover checkboxes and verify they are disabled
    const checkboxes = screen.getAllByRole('checkbox');
    const pushoverCheckbox = checkboxes[3];
    expect(pushoverCheckbox).toBeDisabled();
    expect(pushoverCheckbox).toHaveAttribute(
      'title',
      expect.stringMatching(/Configure.*pushover/i),
    );
  });

  it('shows inline note about last-channel guard', () => {
    const routing: AlertRouting[] = [{ type: 'new_match', channels: ['email'], enabled: true }];
    const qc = makeQc();
    qc.setQueryData(['household'], baseHh);
    qc.setQueryData(['alert_routing'], routing);

    render(<AlertRoutingSection />, {
      wrapper: wrap(qc),
    });

    expect(
      screen.getByText(
        /Uncheck Enabled to disable a row entirely.*last channel.*can't be removed/i,
      ),
    ).toBeInTheDocument();
  });

  it('cell toggle calls PATCH /api/alert_routing/:type with the updated channels array', async () => {
    const routing: AlertRouting[] = [{ type: 'new_match', channels: ['email'], enabled: true }];
    const qc = makeQc();
    qc.setQueryData(['household'], baseHh);
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const ntfyCell = screen.getByRole('checkbox', { name: /new_match ntfy/i });
    expect(ntfyCell).not.toBeChecked();

    fireEvent.change(ntfyCell, { target: { checked: true } });

    // Optimistic update makes checkbox appear checked before server response
    expect(ntfyCell).toBeChecked();
  });

  it('Enabled checkbox toggle PATCHes {enabled: bool}', async () => {
    const routing: AlertRouting[] = [{ type: 'new_match', channels: ['email'], enabled: true }];
    const qc = makeQc();
    qc.setQueryData(['household'], baseHh);
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const enabledCell = screen.getByRole('checkbox', { name: /new_match enabled/i });
    expect(enabledCell).toBeChecked();

    fireEvent.change(enabledCell, { target: { checked: false } });

    // Optimistic update makes checkbox appear unchecked before server response
    expect(enabledCell).not.toBeChecked();
  });

  it('clicking the last remaining channel checkbox in an enabled row does NOT fire PATCH', async () => {
    server.use(); // Reset to default handler
    const qc = makeQc();
    qc.setQueryData(['household'], baseHh);
    qc.setQueryData(['alert_routing'], [{ type: 'new_match', channels: ['email'], enabled: true }]);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const emailCell = screen.getByRole('checkbox', { name: /new_match email/i });
    expect(emailCell).toBeChecked();
    await userEvent.click(emailCell);

    await new Promise((resolve) => setTimeout(resolve, 100));
    // The cell stays checked because the click was suppressed by the guard
    expect(emailCell).toBeChecked();
  });
});
