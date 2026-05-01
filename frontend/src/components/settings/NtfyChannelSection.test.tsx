import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NtfyChannelSection } from './NtfyChannelSection';
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
  email_configured: false,
  ntfy_configured: false,
  pushover_configured: false,
};

const wrap = (qc: QueryClient, household: Household) => {
  qc.setQueryData(['household'], household);
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
};
const makeQc = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

describe('NtfyChannelSection', () => {
  it('renders empty form with default base_url=https://ntfy.sh and empty topic', () => {
    render(<NtfyChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    const baseUrlInput = screen.getByLabelText(/Base URL/i) as HTMLInputElement;
    expect(baseUrlInput.value).toBe('https://ntfy.sh');

    const topicInput = screen.getByLabelText(/Topic/i) as HTMLInputElement;
    expect(topicInput.value).toBe('');

    // Verify other fields are present
    expect(screen.getByLabelText(/Auth Token Env/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send test ntfy/i })).toBeInTheDocument();
  });

  it('save POSTs PATCH with {ntfy_config_json: {base_url, topic}} and auth_token_env absent when blank', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<NtfyChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Fill form
    await user.type(screen.getByLabelText(/Topic/i), 'yas-test');
    // base_url defaults to https://ntfy.sh, no need to change

    // Click save
    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.ntfy_config_json as Record<string, unknown>) || {};
      expect(config.base_url).toBe('https://ntfy.sh');
      expect(config.topic).toBe('yas-test');
      expect(config.auth_token_env).toBeUndefined(); // omitted when blank
    });
  });

  it('disable button → ConfirmDialog confirm → PATCH {ntfy_config_json: null}', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<NtfyChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Click disable button
    await user.click(screen.getByRole('button', { name: /disable channel/i }));

    // Verify confirm dialog appears
    expect(await screen.findByText(/disable ntfy channel/i)).toBeInTheDocument();

    // Click confirm
    await user.click(screen.getByRole('button', { name: /^Disable$/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      expect(captured?.ntfy_config_json).toBeNull();
    });
  });

  it('test-send button is disabled while form is dirty', async () => {
    const user = userEvent.setup();
    render(<NtfyChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Test-send button should be enabled initially (form is clean)
    const testButton = screen.getByRole('button', { name: /send test ntfy/i });
    expect(testButton).not.toBeDisabled();

    // Type into topic field to make form dirty
    await user.type(screen.getByLabelText(/Topic/i), 'test');

    // Test-send button should now be disabled
    expect(testButton).toBeDisabled();
  });

  it('empty topic blocks save', async () => {
    render(<NtfyChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Save button should be disabled with empty topic
    const saveButton = screen.getByRole('button', { name: /^Save/i }) as HTMLButtonElement;
    expect(saveButton).toBeDisabled();
  });
});
