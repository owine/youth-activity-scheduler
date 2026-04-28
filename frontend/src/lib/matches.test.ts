import { describe, it, expect } from 'vitest';
import type { Match } from './types';
import { urgencyOf, groupByUrgency } from './matches';

const now = new Date('2026-04-24T12:00:00Z');

function makeMatch(overrides: Partial<Match['offering']> = {}): Match {
  return {
    kid_id: 1,
    offering_id: 1,
    score: 0.9,
    reasons: {},
    computed_at: '2026-04-24T12:00:00Z',
    offering: {
      id: 1,
      site_id: 1,
      site_name: 'X',
      name: 'T-Ball',
      program_type: 'other',
      age_min: null,
      age_max: null,
      start_date: null,
      end_date: null,
      days_of_week: [],
      time_start: null,
      time_end: null,
      price_cents: null,
      registration_url: null,
      registration_opens_at: null,
      ...overrides,
    },
  };
}

describe('urgencyOf', () => {
  it('returns opens-this-week when registration opens tomorrow', () => {
    const m = makeMatch({ registration_opens_at: '2026-04-25T12:00:00Z' });
    expect(urgencyOf(m, now)).toBe('opens-this-week');
  });

  it('returns starting-soon when starts in 5 days and no opens date', () => {
    const m = makeMatch({ start_date: '2026-04-29T12:00:00Z' });
    expect(urgencyOf(m, now)).toBe('starting-soon');
  });

  it('returns later when no opens and no start date', () => {
    const m = makeMatch();
    expect(urgencyOf(m, now)).toBe('later');
  });

  it('falls through to start_date when opens is more than 7 days away', () => {
    const m = makeMatch({
      registration_opens_at: '2026-05-10T12:00:00Z', // ~16 days
      start_date: '2026-04-30T12:00:00Z', // 6 days
    });
    expect(urgencyOf(m, now)).toBe('starting-soon');
  });

  it('returns later when start_date is far future', () => {
    const m = makeMatch({ start_date: '2026-08-01T12:00:00Z' });
    expect(urgencyOf(m, now)).toBe('later');
  });
});

describe('groupByUrgency', () => {
  it('buckets matches into the three urgency groups', () => {
    const opens = makeMatch({ registration_opens_at: '2026-04-25T12:00:00Z' });
    const soon = makeMatch({ start_date: '2026-04-29T12:00:00Z' });
    const later = makeMatch();
    const groups = groupByUrgency([opens, soon, later], now);
    expect(groups['opens-this-week']).toHaveLength(1);
    expect(groups['starting-soon']).toHaveLength(1);
    expect(groups.later).toHaveLength(1);
  });
});
