import { describe, it, expect } from 'vitest';
import {
  groupByOffering,
  applyFilters,
  sortOfferingRows,
  chipsForOffering,
  defaultFilterState,
} from './offeringsFilters';
import type { Match, OfferingSummary, FilterState, Household, KidBrief } from './types';

const baseOffering = (over: Partial<OfferingSummary> = {}): OfferingSummary => ({
  id: 1,
  name: 'Soccer',
  program_type: 'soccer',
  age_min: 5,
  age_max: 10,
  start_date: '2026-06-01',
  end_date: '2026-08-31',
  days_of_week: ['mon', 'wed'],
  time_start: '17:00:00',
  time_end: '18:00:00',
  price_cents: 12000,
  registration_url: null,
  site_id: 1,
  registration_opens_at: null,
  site_name: 'TestSite',
  muted_until: null,
  location_lat: null,
  location_lon: null,
  ...over,
});

const baseMatch = (over: Partial<Match> = {}): Match => ({
  kid_id: 1,
  offering_id: 1,
  score: 0.8,
  reasons: { score_breakdown: { distance: 0.5 } },
  computed_at: '2026-05-01T00:00:00Z',
  offering: baseOffering(),
  ...over,
});

const baseHousehold = (over: Partial<Household> = {}): Household => ({
  id: 1,
  home_location_id: null,
  home_address: null,
  home_location_name: null,
  home_lat: null,
  home_lon: null,
  email_configured: false,
  ntfy_configured: false,
  pushover_configured: false,
  default_max_distance_mi: null,
  digest_time: '07:00',
  quiet_hours_start: null,
  quiet_hours_end: null,
  daily_llm_cost_cap_usd: 1.0,
  ...over,
});

const baseFilters = (over: Partial<FilterState> = {}): FilterState => ({
  ...defaultFilterState([1, 2]),
  ...over,
});

describe('groupByOffering', () => {
  it('collapses multiple kid matches per offering into one row sorted by score desc', () => {
    const m1 = baseMatch({
      kid_id: 1,
      score: 0.7,
      offering_id: 10,
      offering: baseOffering({ id: 10 }),
    });
    const m2 = baseMatch({
      kid_id: 2,
      score: 0.9,
      offering_id: 10,
      offering: baseOffering({ id: 10 }),
    });
    const m3 = baseMatch({
      kid_id: 1,
      score: 0.8,
      offering_id: 20,
      offering: baseOffering({ id: 20 }),
    });
    const rows = groupByOffering([m1, m2, m3]);
    expect(rows).toHaveLength(2);
    const row10 = rows.find((r) => r.offering.id === 10)!;
    expect(row10.matches.map((m) => m.kid_id)).toEqual([2, 1]); // 0.9 first
  });
});

describe('applyFilters', () => {
  it('kid filter drops non-selected kids and removes empty rows', () => {
    const m = baseMatch({ kid_id: 2 });
    const rows = groupByOffering([m]);
    const out = applyFilters(rows, baseFilters({ selectedKidIds: [1] }), baseHousehold());
    expect(out).toEqual([]);
  });

  it('days AND-match: row with [mon,wed,fri] passes [mon,wed]; fails [mon,sat]', () => {
    const row = groupByOffering([
      baseMatch({ offering: baseOffering({ days_of_week: ['mon', 'wed', 'fri'] }) }),
    ]);
    expect(applyFilters(row, baseFilters({ days: ['mon', 'wed'] }), baseHousehold())).toHaveLength(
      1,
    );
    expect(applyFilters(row, baseFilters({ days: ['mon', 'sat'] }), baseHousehold())).toHaveLength(
      0,
    );
  });

  it('reg-timing branches: opens_this_week / open_now / closed', () => {
    const now = new Date('2026-05-15T12:00:00Z');
    const inFiveDays = new Date(now.getTime() + 5 * 86400000).toISOString();
    const yesterday = new Date(now.getTime() - 86400000).toISOString();
    const rowOpens = groupByOffering([
      baseMatch({ offering: baseOffering({ registration_opens_at: inFiveDays }) }),
    ]);
    const rowOpen = groupByOffering([
      baseMatch({
        offering: baseOffering({ registration_opens_at: yesterday, end_date: '2026-12-31' }),
      }),
    ]);
    expect(
      applyFilters(rowOpens, baseFilters({ regTiming: 'opens_this_week' }), baseHousehold(), now),
    ).toHaveLength(1);
    expect(
      applyFilters(rowOpen, baseFilters({ regTiming: 'open_now' }), baseHousehold(), now),
    ).toHaveLength(1);
  });

  it('distance filter passes through when household lat/lon null; applies haversine when both sides have coords', () => {
    const offering = baseOffering({ location_lat: 41.88, location_lon: -87.63 }); // Chicago
    const row = groupByOffering([baseMatch({ offering })]);
    // Household null → pass-through
    expect(applyFilters(row, baseFilters({ maxDistanceMi: 10 }), baseHousehold())).toHaveLength(1);
    // Household at same coords → distance 0, passes any maxDistanceMi
    const closeHh = baseHousehold({ home_lat: 41.88, home_lon: -87.63 });
    expect(applyFilters(row, baseFilters({ maxDistanceMi: 1 }), closeHh)).toHaveLength(1);
    // Household far away → exceeds 10 miles
    const farHh = baseHousehold({ home_lat: 40.0, home_lon: -88.0 });
    expect(applyFilters(row, baseFilters({ maxDistanceMi: 10 }), farHh)).toHaveLength(0);
  });

  it('age range overlap: row [5-10] passes [8,12]; fails [11,14]', () => {
    const row = groupByOffering([
      baseMatch({ offering: baseOffering({ age_min: 5, age_max: 10 }) }),
    ]);
    expect(applyFilters(row, baseFilters({ ageMin: 8, ageMax: 12 }), baseHousehold())).toHaveLength(
      1,
    );
    expect(
      applyFilters(row, baseFilters({ ageMin: 11, ageMax: 14 }), baseHousehold()),
    ).toHaveLength(0);
  });

  it('watchlist-only drops rows where no match has reasons.watchlist_hit', () => {
    const matches = [
      baseMatch({ kid_id: 1, reasons: { watchlist_hit: null, score_breakdown: {} } }),
      baseMatch({ kid_id: 2, reasons: { watchlist_hit: { entry_id: 5 }, score_breakdown: {} } }),
    ];
    const rows = groupByOffering(matches);
    expect(applyFilters(rows, baseFilters({ watchlistOnly: true }), baseHousehold())).toHaveLength(
      1,
    );
  });

  it('time-of-day filter: HH:MM string compare with HH:MM:SS source slice', () => {
    const morning = baseOffering({ id: 1, time_start: '09:00:00', time_end: '10:00:00' });
    const evening = baseOffering({ id: 2, time_start: '17:00:00', time_end: '18:00:00' });
    const rows = groupByOffering([
      baseMatch({ offering: morning, offering_id: 1 }),
      baseMatch({ offering: evening, offering_id: 2 }),
    ]);
    const out = applyFilters(
      rows,
      baseFilters({ timeOfDayMin: '15:00', timeOfDayMax: '20:00' }),
      baseHousehold(),
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.offering.id).toBe(2);
  });
});

describe('sortOfferingRows', () => {
  it('best_score desc with id desc tiebreaker', () => {
    const rows = [
      { offering: baseOffering({ id: 1 }), matches: [baseMatch({ score: 0.7 })] },
      { offering: baseOffering({ id: 2 }), matches: [baseMatch({ score: 0.7 })] },
      { offering: baseOffering({ id: 3 }), matches: [baseMatch({ score: 0.9 })] },
    ];
    const out = sortOfferingRows(rows, 'best_score');
    expect(out.map((r) => r.offering.id)).toEqual([3, 2, 1]); // 0.9 first; tied 0.7 by id desc
  });

  it('soonest_start with nulls last', () => {
    const rows = [
      { offering: baseOffering({ id: 1, start_date: null }), matches: [baseMatch()] },
      { offering: baseOffering({ id: 2, start_date: '2026-06-01' }), matches: [baseMatch()] },
      { offering: baseOffering({ id: 3, start_date: '2026-05-01' }), matches: [baseMatch()] },
    ];
    expect(sortOfferingRows(rows, 'soonest_start').map((r) => r.offering.id)).toEqual([3, 2, 1]);
  });
});

describe('chipsForOffering', () => {
  const kidsById = new Map<number, KidBrief>([
    [1, { id: 1, name: 'Sam', dob: '2018-01-01', interests: ['soccer'], active: true }],
  ]);

  it('returns empty array when no chips apply', () => {
    const row = {
      offering: baseOffering({ program_type: 'unknown' }),
      matches: [baseMatch({ score: 0.5, reasons: { score_breakdown: {} } })],
    };
    const chips = chipsForOffering(row, new Map(), new Date('2026-01-01'));
    expect(chips).toHaveLength(0);
  });

  it('watchlist chip has highest priority', () => {
    const row = {
      offering: baseOffering(),
      matches: [baseMatch({ reasons: { watchlist_hit: { entry_id: 1 }, score_breakdown: {} } })],
    };
    const chips = chipsForOffering(row, kidsById, new Date('2026-01-01'));
    expect(chips[0]!.kind).toBe('watchlist');
  });

  it('top_match chip for score >= 0.85', () => {
    const row = {
      offering: baseOffering(),
      matches: [baseMatch({ score: 0.85, reasons: { score_breakdown: {} } })],
    };
    const chips = chipsForOffering(row, new Map(), new Date('2026-01-01'));
    expect(chips.some((c) => c.kind === 'top_match')).toBe(true);
  });

  it('opens_this_week chip when registration_opens_at in [now, now+7d]', () => {
    const now = new Date('2026-01-01T00:00:00Z');
    const inThreeDays = new Date(now.getTime() + 3 * 86400000).toISOString();
    const row = {
      offering: baseOffering({ registration_opens_at: inThreeDays }),
      matches: [baseMatch({ reasons: { score_breakdown: {} } })],
    };
    const chips = chipsForOffering(row, new Map(), now);
    expect(chips.some((c) => c.kind === 'opens_this_week')).toBe(true);
  });

  it('in_interests chip resolves through kidsById', () => {
    const row = {
      offering: baseOffering({ program_type: 'soccer' }),
      matches: [baseMatch({ kid_id: 1, reasons: { score_breakdown: {} } })],
    };
    const chips = chipsForOffering(row, kidsById, new Date('2026-01-01'));
    expect(chips.some((c) => c.kind === 'in_interests')).toBe(true);
  });

  it('near_home requires score_breakdown.distance >= 0.7', () => {
    const lowDist = {
      offering: baseOffering(),
      matches: [baseMatch({ reasons: { score_breakdown: { distance: 0.5 } } })],
    };
    expect(
      chipsForOffering(lowDist, new Map(), new Date('2026-01-01')).some(
        (c) => c.kind === 'near_home',
      ),
    ).toBe(false);

    const highDist = {
      offering: baseOffering(),
      matches: [baseMatch({ reasons: { score_breakdown: { distance: 0.8 } } })],
    };
    expect(
      chipsForOffering(highDist, new Map(), new Date('2026-01-01')).some(
        (c) => c.kind === 'near_home',
      ),
    ).toBe(true);
  });

  it('returns max 3 chips in priority order', () => {
    const now = new Date('2026-01-01T00:00:00Z');
    const inThreeDays = new Date(now.getTime() + 3 * 86400000).toISOString();
    const row = {
      offering: baseOffering({
        program_type: 'soccer',
        registration_opens_at: inThreeDays,
      }),
      matches: [
        baseMatch({
          kid_id: 1,
          score: 0.9,
          reasons: {
            watchlist_hit: { entry_id: 1 },
            score_breakdown: { distance: 0.8 },
          },
        }),
      ],
    };
    const chips = chipsForOffering(row, kidsById, now);
    expect(chips.length).toBeLessThanOrEqual(3);
    // Verify priority order: watchlist first
    expect(chips[0]!.kind).toBe('watchlist');
  });
});

describe('defaultFilterState', () => {
  it('returns canonical defaults with selectedKidIds set to allKidIds', () => {
    const state = defaultFilterState([1, 2, 3]);
    expect(state.selectedKidIds).toEqual([1, 2, 3]);
    expect(state.minScore).toBe(0.6);
    expect(state.sort).toBe('best_score');
    expect(state.hideMuted).toBe(true);
    expect(state.programTypes).toEqual([]);
    expect(state.days).toEqual([]);
    expect(state.regTiming).toBe('any');
  });
});
