import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MatchReasonChips } from './MatchReasonChips';
import type { OfferingRow, KidBrief, Match, OfferingSummary } from '@/lib/types';

const makeOffering = (over: Partial<OfferingSummary> = {}): OfferingSummary => ({
  id: 1,
  name: 'X',
  program_type: 'soccer',
  age_min: null,
  age_max: null,
  start_date: null,
  end_date: null,
  days_of_week: [],
  time_start: null,
  time_end: null,
  price_cents: null,
  registration_url: null,
  site_id: 1,
  registration_opens_at: null,
  site_name: 'S',
  muted_until: null,
  location_lat: null,
  location_lon: null,
  ...over,
});

const makeMatch = (over: Partial<Match> = {}): Match => ({
  kid_id: 1,
  offering_id: 1,
  score: 0.5,
  reasons: { score_breakdown: {} },
  computed_at: '2026-05-01T00:00:00Z',
  offering: makeOffering(),
  ...over,
});

const makeRow = (matches: Match[], offering = makeOffering()): OfferingRow => ({
  offering,
  matches,
});

const kidsById = new Map<number, KidBrief>([
  [
    1,
    {
      id: 1,
      name: 'Sam',
      dob: '2018-01-01',
      interests: ['soccer'],
      active: true,
    },
  ],
]);

describe('MatchReasonChips', () => {
  it('renders nothing when no chips apply', () => {
    const row = makeRow([makeMatch({ score: 0.5 })], makeOffering({ program_type: 'unknown' }));
    const { container } = render(
      <MatchReasonChips row={row} kidsById={new Map()} now={new Date('2026-01-01')} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('Watchlist always first when present (priority order)', () => {
    const row = makeRow([
      makeMatch({
        score: 0.9,
        reasons: { watchlist_hit: { entry_id: 1 }, score_breakdown: {} },
      }),
    ]);
    render(<MatchReasonChips row={row} kidsById={kidsById} now={new Date('2026-01-01')} />);
    const labels = screen.getAllByRole('status').map((el) => el.textContent);
    expect(labels[0]).toMatch(/Watchlist/);
    expect(labels[1]).toMatch(/Top match/);
  });

  it('only top 3 chips shown when > 3 apply', () => {
    const row = makeRow(
      [
        makeMatch({
          score: 0.9,
          reasons: {
            watchlist_hit: { entry_id: 1 },
            score_breakdown: { distance: 0.9 },
          },
        }),
      ],
      makeOffering({
        program_type: 'soccer',
        registration_opens_at: '2026-01-03T00:00:00Z',
      }),
    );
    render(
      <MatchReasonChips row={row} kidsById={kidsById} now={new Date('2026-01-01T00:00:00Z')} />,
    );
    expect(screen.getAllByRole('status')).toHaveLength(3);
  });

  it('In-interests resolves through kidsById', () => {
    const row = makeRow([makeMatch({ kid_id: 1 })], makeOffering({ program_type: 'soccer' }));
    render(<MatchReasonChips row={row} kidsById={kidsById} now={new Date('2026-01-01')} />);
    expect(screen.getByText(/In interests/)).toBeInTheDocument();
  });

  it('Near home requires reasons.score_breakdown.distance >= 0.7', () => {
    const lowDist = makeRow([makeMatch({ reasons: { score_breakdown: { distance: 0.5 } } })]);
    const { rerender, container } = render(
      <MatchReasonChips row={lowDist} kidsById={new Map()} now={new Date('2026-01-01')} />,
    );
    expect(container.firstChild).toBeNull();
    const highDist = makeRow([makeMatch({ reasons: { score_breakdown: { distance: 0.8 } } })]);
    rerender(<MatchReasonChips row={highDist} kidsById={new Map()} now={new Date('2026-01-01')} />);
    expect(screen.getByText(/Near home/)).toBeInTheDocument();
  });
});
