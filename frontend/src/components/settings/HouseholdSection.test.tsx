import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HouseholdSection } from './HouseholdSection';
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

describe('HouseholdSection', () => {
  it('pre-populates from useHousehold data', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), { ...baseHh, digest_time: '08:30', daily_llm_cost_cap_usd: 2.5 }),
    });
    expect(screen.getByLabelText(/digest time/i)).toHaveValue('08:30');
    expect(screen.getByLabelText(/daily llm cost cap/i)).toHaveValue(2.5);
  });

  it('saves valid edits via PATCH /api/household', async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseHh, digest_time: '09:00' });
      }),
    );
    render(<HouseholdSection />, { wrapper: wrap(makeQc(), baseHh) });
    const digest = screen.getByLabelText(/digest time/i);
    await userEvent.clear(digest);
    await userEvent.type(digest, '09:00');
    const saveBtn = screen.getByRole('button', { name: /save/i });
    expect(saveBtn).not.toBeDisabled();
    await userEvent.click(saveBtn);
    await waitFor(() => expect(captured).not.toBeNull());
    expect((captured as unknown as Record<string, unknown>).digest_time).toBe('09:00');
  });

  it('renders green pill when home_lat/home_lon are set', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), {
        ...baseHh,
        home_address: '123 Main',
        home_lat: 12.34,
        home_lon: 56.78,
      }),
    });
    expect(screen.getByText(/Geocoded:.*12\.34/)).toBeInTheDocument();
  });

  it('renders amber pill when address is set but lat/lon are null', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), {
        ...baseHh,
        home_address: '123 Main',
        home_lat: null,
        home_lon: null,
      }),
    });
    expect(screen.getByText(/Geocoding failed/)).toBeInTheDocument();
  });

  it('blocks save with invalid digest_time', async () => {
    render(<HouseholdSection />, { wrapper: wrap(makeQc(), baseHh) });
    const digest = screen.getByLabelText(/digest time/i);
    // Clear and type invalid time, then blur to trigger validation
    await userEvent.clear(digest);
    await userEvent.type(digest, 'invalid');
    await userEvent.tab(); // Blur the field
    // Check that the button becomes disabled
    await waitFor(
      () => {
        const saveBtn = screen.getByRole('button', { name: /save/i });
        expect(saveBtn).toBeDisabled();
      },
      { timeout: 2000 },
    );
  });
});
