import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PushoverChannelSection } from './PushoverChannelSection';
import type { Household } from '@/lib/types';

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
};

const wrap = (qc: QueryClient, household: Household) => {
  qc.setQueryData(['household'], household);
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
};
const makeQc = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

describe('PushoverChannelSection', () => {
  it('renders empty form with emergency_retry_s=60, emergency_expire_s=3600 defaults; advanced details collapsed', () => {
    render(<PushoverChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Verify required fields are present and empty
    expect((screen.getByLabelText(/User Key Env/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/App Token Env/i) as HTMLInputElement).value).toBe('');

    // Verify advanced fields have correct defaults
    expect((screen.getByLabelText(/Emergency Retry/i) as HTMLInputElement).value).toBe('60');
    expect((screen.getByLabelText(/Emergency Expire/i) as HTMLInputElement).value).toBe('3600');

    // Verify devices field is present
    expect(screen.getByLabelText(/Devices/i)).toBeInTheDocument();

    // Verify test button is present
    expect(screen.getByRole('button', { name: /send test pushover/i })).toBeInTheDocument();

    // Verify details element exists and is NOT open
    const detailsElement = screen.getByText(/Advanced/).closest('details') as HTMLDetailsElement;
    expect(detailsElement).toBeInTheDocument();
    expect(detailsElement.open).toBe(false);
  });

  it('save sends PATCH with right shape; devices absent when blank', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<PushoverChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Fill required fields
    await user.type(screen.getByLabelText(/User Key Env/i), 'YAS_PUSHOVER_USER_KEY');
    await user.type(screen.getByLabelText(/App Token Env/i), 'YAS_PUSHOVER_APP_TOKEN');

    // Click save
    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.pushover_config_json as Record<string, unknown>) || {};
      expect(config.user_key_env).toBe('YAS_PUSHOVER_USER_KEY');
      expect(config.app_token_env).toBe('YAS_PUSHOVER_APP_TOKEN');
      expect(config.devices).toBeUndefined(); // omitted when blank
      expect(config.emergency_retry_s).toBe(60);
      expect(config.emergency_expire_s).toBe(3600);
    });
  });

  it('save with comma-separated devices → patch contains devices: [...]', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<PushoverChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Fill required fields
    await user.type(screen.getByLabelText(/User Key Env/i), 'YAS_PUSHOVER_USER_KEY');
    await user.type(screen.getByLabelText(/App Token Env/i), 'YAS_PUSHOVER_APP_TOKEN');
    await user.type(screen.getByLabelText(/Devices/i), 'phone, tablet , watch');

    // Click save
    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.pushover_config_json as Record<string, unknown>) || {};
      expect(config.devices).toEqual(['phone', 'tablet', 'watch']);
    });
  });

  it('disable button → ConfirmDialog confirm → PATCH {pushover_config_json: null}', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<PushoverChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Click disable button
    await user.click(screen.getByRole('button', { name: /disable channel/i }));

    // Verify confirm dialog appears
    expect(await screen.findByText(/disable pushover channel/i)).toBeInTheDocument();

    // Click confirm
    await user.click(screen.getByRole('button', { name: /^Disable$/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      expect(captured?.pushover_config_json).toBeNull();
    });
  });

  it('missing user_key_env blocks save', async () => {
    render(<PushoverChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Fill only app_token_env
    await userEvent.type(screen.getByLabelText(/App Token Env/i), 'YAS_PUSHOVER_APP_TOKEN');

    // Save button should be disabled with missing user_key_env
    const saveButton = screen.getByRole('button', { name: /^Save/i }) as HTMLButtonElement;
    expect(saveButton).toBeDisabled();
  });
});
