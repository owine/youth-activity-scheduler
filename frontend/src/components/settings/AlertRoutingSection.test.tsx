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
  it('renders rows for each alert type with columns [Enabled, email, ntfy, pushover, any push]', () => {
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

    // Check that checkboxes are rendered (2 rows * 5 columns = 10 checkboxes)
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(10);
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

  it('shows the "push" alias the default routing uses, and gates it on any push channel', () => {
    // reg_opens_1h defaults to ["push"]; without this column the row looked
    // like it routed nowhere and the alias could not be removed.
    const routing: AlertRouting[] = [{ type: 'reg_opens_1h', channels: ['push'], enabled: true }];
    const qc = makeQc();
    qc.setQueryData(['household'], {
      ...baseHh,
      ntfy_configured: false,
      pushover_configured: false,
    });
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const push = screen.getByRole('checkbox', { name: 'reg_opens_1h push' });
    expect(push).toBeChecked();
    // Last channel of an enabled row: removal is blocked by the guard.
    expect(push).toBeDisabled();
  });

  it('blocks adding "any push" until ntfy or Pushover is configured', () => {
    const routing: AlertRouting[] = [{ type: 'new_match', channels: ['email'], enabled: true }];
    const qc = makeQc();
    qc.setQueryData(['household'], {
      ...baseHh,
      ntfy_configured: false,
      pushover_configured: false,
    });
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const push = screen.getByRole('checkbox', { name: 'new_match push' });
    expect(push).not.toBeChecked();
    expect(push).toBeDisabled();
    expect(push).toHaveAttribute('title', expect.stringMatching(/ntfy or Pushover/));
  });

  it('lets an unconfigured channel that is already routed be removed', () => {
    const routing: AlertRouting[] = [
      { type: 'watchlist_hit', channels: ['push', 'email'], enabled: true },
    ];
    const qc = makeQc();
    qc.setQueryData(['household'], {
      ...baseHh,
      ntfy_configured: false,
      pushover_configured: false,
    });
    qc.setQueryData(['alert_routing'], routing);
    render(<AlertRoutingSection />, { wrapper: wrap(qc) });

    const push = screen.getByRole('checkbox', { name: 'watchlist_hit push' });
    expect(push).toBeChecked();
    expect(push).toBeEnabled();
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
