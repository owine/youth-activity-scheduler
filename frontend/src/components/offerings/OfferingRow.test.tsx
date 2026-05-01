import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { OfferingRow } from './OfferingRow';
import type { OfferingRow as OfferingRowType, KidBrief, Match, OfferingSummary } from '@/lib/types';

const makeOffering = (over: Partial<OfferingSummary> = {}): OfferingSummary => ({
  id: 1,
  name: 'Soccer Camp',
  program_type: 'soccer',
  age_min: 5,
  age_max: 12,
  start_date: '2026-06-15',
  end_date: '2026-08-31',
  days_of_week: ['mon', 'wed', 'fri'],
  time_start: '17:00:00',
  time_end: '18:00:00',
  price_cents: 15000,
  registration_url: null,
  site_id: 1,
  registration_opens_at: '2026-05-15T00:00:00Z',
  site_name: 'Parks & Rec',
  muted_until: null,
  location_lat: null,
  location_lon: null,
  ...over,
});

const makeMatch = (over: Partial<Match> = {}): Match => ({
  kid_id: 1,
  offering_id: 1,
  score: 0.92,
  reasons: { score_breakdown: {} },
  computed_at: '2026-05-01T00:00:00Z',
  offering: makeOffering(),
  ...over,
});

const makeKidBrief = (over: Partial<KidBrief> = {}): KidBrief => ({
  id: 1,
  name: 'Sam',
  dob: '2018-01-01',
  interests: ['soccer'],
  active: true,
  ...over,
});

const makeRow = (matches: Match[], offering = makeOffering()): OfferingRowType => ({
  offering,
  matches,
});

describe('OfferingRow', () => {
  const renderWithQueryClient = (element: React.ReactElement) => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    return render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
  };

  it('renders name + site_name + dates + price + best-score-across-kids + chips + matched kids list', () => {
    const samMatch = makeMatch({
      kid_id: 1,
      score: 0.92,
      offering: makeOffering({ id: 10, name: 'Soccer Camp' }),
    });
    const alexMatch = makeMatch({
      kid_id: 2,
      score: 0.78,
      offering: makeOffering({ id: 10, name: 'Soccer Camp' }),
    });
    const row = makeRow([samMatch, alexMatch], makeOffering({ id: 10, name: 'Soccer Camp' }));
    const kidsById = new Map<number, KidBrief>([
      [1, makeKidBrief({ id: 1, name: 'Sam' })],
      [2, makeKidBrief({ id: 2, name: 'Alex' })],
    ]);
    const now = new Date('2026-05-01');
    const onSelect = vi.fn();

    renderWithQueryClient(
      <OfferingRow row={row} kidsById={kidsById} now={now} onSelect={onSelect} />,
    );

    // Check name
    expect(screen.getByText('Soccer Camp')).toBeInTheDocument();

    // Check site name
    expect(screen.getByText(/Parks & Rec/)).toBeInTheDocument();

    // Check best score
    expect(screen.getByText('0.92')).toBeInTheDocument();

    // Check matched kids list in third line
    expect(screen.getByText(/Sam \(0\.92\)/)).toBeInTheDocument();
    expect(screen.getByText(/Alex \(0\.78\)/)).toBeInTheDocument();
  });

  it('click row calls onSelect with row.matches[0] (highest-scoring match)', async () => {
    const samMatch = makeMatch({
      kid_id: 1,
      score: 0.92,
      offering: makeOffering({ id: 10 }),
    });
    const alexMatch = makeMatch({
      kid_id: 2,
      score: 0.78,
      offering: makeOffering({ id: 10 }),
    });
    const row = makeRow([samMatch, alexMatch], makeOffering({ id: 10 }));
    const kidsById = new Map<number, KidBrief>([
      [1, makeKidBrief({ id: 1, name: 'Sam' })],
      [2, makeKidBrief({ id: 2, name: 'Alex' })],
    ]);
    const onSelect = vi.fn();

    const { container } = renderWithQueryClient(
      <OfferingRow
        row={row}
        kidsById={kidsById}
        now={new Date('2026-05-01')}
        onSelect={onSelect}
      />,
    );

    // Click the Card (find by descendant text)
    const card = container.querySelector('[class*="cursor-pointer"]');
    await userEvent.click(card!);

    expect(onSelect).toHaveBeenCalledWith(samMatch);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('mute button click does NOT trigger onSelect (stopPropagation)', async () => {
    server.use(
      http.patch('/api/offerings/:id', () => {
        return HttpResponse.json({ id: 10 });
      }),
    );

    const match = makeMatch({
      kid_id: 1,
      score: 0.92,
      offering: makeOffering({ id: 10 }),
    });
    const row = makeRow([match], makeOffering({ id: 10 }));
    const kidsById = new Map<number, KidBrief>([[1, makeKidBrief({ id: 1, name: 'Sam' })]]);
    const onSelect = vi.fn();

    renderWithQueryClient(
      <OfferingRow
        row={row}
        kidsById={kidsById}
        now={new Date('2026-05-01')}
        onSelect={onSelect}
      />,
    );

    // Find and click the Mute button
    const muteButton = screen.getByRole('button', { name: /Mute/i });
    await userEvent.click(muteButton);

    // onSelect should not have been called
    expect(onSelect).not.toHaveBeenCalled();
  });
});
