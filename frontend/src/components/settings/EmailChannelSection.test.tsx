import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EmailChannelSection } from './EmailChannelSection';
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

describe('EmailChannelSection', () => {
  it('renders empty form with transport=smtp default + smtp fields visible', () => {
    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Verify transport field defaults to smtp
    const transportSelect = screen.getByLabelText(/Transport/i) as HTMLSelectElement;
    expect(transportSelect.value).toBe('smtp');

    // Verify smtp-specific fields are visible
    expect(screen.getByLabelText(/SMTP Host/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/SMTP Port/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/From Address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/To Addresses/i)).toBeInTheDocument();

    // Verify send test button is present
    expect(screen.getByRole('button', { name: /send test email/i })).toBeInTheDocument();
  });

  it('switching to forwardemail hides smtp fields, shows api_token_value', async () => {
    const user = userEvent.setup();
    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Change transport to forwardemail
    const transportSelect = screen.getByLabelText(/Transport/i) as HTMLSelectElement;
    await user.selectOptions(transportSelect, 'forwardemail');

    // Verify smtp fields are hidden
    expect(screen.queryByLabelText(/SMTP Host/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/SMTP Port/i)).not.toBeInTheDocument();

    // Verify forwardemail-specific fields are visible
    expect(screen.getByLabelText(/ForwardEmail API Token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/From Address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/To Addresses/i)).toBeInTheDocument();
  });

  it('valid smtp save sends correct PATCH payload', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Fill smtp form
    await user.type(screen.getByLabelText(/SMTP Host/i), 'smtp.example.com');
    await user.clear(screen.getByLabelText(/SMTP Port/i));
    await user.type(screen.getByLabelText(/SMTP Port/i), '587');
    await user.type(screen.getByLabelText(/From Address/i), 'noreply@example.com');
    await user.type(
      screen.getByLabelText(/To Addresses/i),
      'admin@example.com, support@example.com',
    );

    // Click save
    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.smtp_config_json as Record<string, unknown>) || {};
      expect(config.transport).toBe('smtp');
      expect(config.host).toBe('smtp.example.com');
      expect(config.port).toBe(587);
      expect(config.from_addr).toBe('noreply@example.com');
      expect(config.to_addrs).toEqual(['admin@example.com', 'support@example.com']);
      expect(config.username).toBeUndefined(); // omitted when blank
    });
  });

  it('valid forwardemail save sends correct PATCH payload', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Change transport to forwardemail
    const transportSelect = screen.getByLabelText(/Transport/i) as HTMLSelectElement;
    await user.selectOptions(transportSelect, 'forwardemail');

    // Fill forwardemail form
    await user.type(screen.getByLabelText(/ForwardEmail API Token/i), 'secret-api-token');
    await user.type(screen.getByLabelText(/From Address/i), 'noreply@forwardemail.example.com');
    await user.type(screen.getByLabelText(/To Addresses/i), 'admin@example.com');

    // Click save
    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.smtp_config_json as Record<string, unknown>) || {};
      expect(config.transport).toBe('forwardemail');
      expect(config.api_token_value).toBe('secret-api-token');
      expect(config.from_addr).toBe('noreply@forwardemail.example.com');
      expect(config.to_addrs).toEqual(['admin@example.com']);
    });
  });

  it('forwardemail save with no api_token_value succeeds and omits the key', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    const transportSelect = screen.getByLabelText(/Transport/i) as HTMLSelectElement;
    await user.selectOptions(transportSelect, 'forwardemail');

    // Leave api_token_value blank — server falls back to YAS_FORWARDEMAIL_API_TOKEN env var.
    await user.type(screen.getByLabelText(/From Address/i), 'noreply@forwardemail.example.com');
    await user.type(screen.getByLabelText(/To Addresses/i), 'admin@example.com');

    await user.click(screen.getByRole('button', { name: /^Save/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      const config = (captured?.smtp_config_json as Record<string, unknown>) || {};
      expect(config.transport).toBe('forwardemail');
      expect(config.api_token_value).toBeUndefined();
      expect(config.from_addr).toBe('noreply@forwardemail.example.com');
      expect(config.to_addrs).toEqual(['admin@example.com']);
    });
  });

  it('disable button → ConfirmDialog confirm → PATCH {smtp_config_json: null}', async () => {
    const user = userEvent.setup();
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(baseHh);
      }),
    );

    render(<EmailChannelSection />, { wrapper: wrap(makeQc(), baseHh) });

    // Click disable button
    await user.click(screen.getByRole('button', { name: /disable channel/i }));

    // Verify confirm dialog appears
    expect(await screen.findByText(/disable email channel/i)).toBeInTheDocument();

    // Click confirm
    await user.click(screen.getByRole('button', { name: /^Disable$/i }));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      expect(captured?.smtp_config_json).toBeNull();
    });
  });
});
