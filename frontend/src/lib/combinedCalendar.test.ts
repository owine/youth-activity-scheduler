import { describe, it, expect } from 'vitest';
import { mergeKidCalendars } from './combinedCalendar';
import type { KidBrief, KidCalendarResponse, CalendarEvent } from './types';

const sam: KidBrief = {
  id: 1,
  name: 'Sam',
  dob: '2019-05-01',
  interests: [],
  active: true,
};
const lila: KidBrief = {
  id: 2,
  name: 'Lila',
  dob: '2017-08-12',
  interests: [],
  active: true,
};

function ev(
  date: string,
  title: string,
  kind: CalendarEvent['kind'] = 'enrollment',
  time_start: string | null = '09:00:00',
): CalendarEvent {
  return {
    id: `${kind}:${title}:${date}`,
    kind,
    date,
    time_start,
    time_end: time_start ? '10:00:00' : null,
    all_day: time_start === null,
    title,
  };
}

const samResp = (events: CalendarEvent[]): KidCalendarResponse => ({
  kid_id: 1,
  from: '2026-05-10',
  to: '2026-05-16',
  events,
});
const lilaResp = (events: CalendarEvent[]): KidCalendarResponse => ({
  kid_id: 2,
  from: '2026-05-10',
  to: '2026-05-16',
  events,
});

describe('mergeKidCalendars', () => {
  it('flattens responses and prefixes title with kid name', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'T-Ball')]), lilaResp([ev('2026-05-13', 'Soccer')])],
      new Map([
        [1, sam],
        [2, lila],
      ]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out).toHaveLength(2);
    expect(out.map((e) => e.title).sort()).toEqual(['Lila: Soccer', 'Sam: T-Ball']);
    expect(out.every((e) => typeof e.kid_id === 'number')).toBe(true);
  });

  it('sorts by (date, time_start)', () => {
    const out = mergeKidCalendars(
      [
        samResp([
          ev('2026-05-14', 'B', 'enrollment', '08:00:00'),
          ev('2026-05-13', 'A', 'enrollment', '09:00:00'),
        ]),
        lilaResp([ev('2026-05-13', 'C', 'enrollment', '08:00:00')]),
      ],
      new Map([
        [1, sam],
        [2, lila],
      ]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out.map((e) => e.title)).toEqual(['Lila: C', 'Sam: A', 'Sam: B']);
  });

  it('filters by kidIds', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'A')]), lilaResp([ev('2026-05-13', 'B')])],
      new Map([
        [1, sam],
        [2, lila],
      ]),
      { kidIds: [1], types: null, includeMatches: true },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: A');
  });

  it('filters by types', () => {
    const out = mergeKidCalendars(
      [
        samResp([
          ev('2026-05-13', 'A', 'enrollment'),
          ev('2026-05-13', 'B', 'unavailability', null),
        ]),
      ],
      new Map([[1, sam]]),
      { kidIds: null, types: ['unavailability'], includeMatches: true },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: B');
  });

  it('drops match events when includeMatches=false', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'A', 'enrollment'), ev('2026-05-13', 'M', 'match')])],
      new Map([[1, sam]]),
      { kidIds: null, types: null, includeMatches: false },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: A');
  });

  it('returns empty for empty responses', () => {
    const out = mergeKidCalendars([], new Map(), {
      kidIds: null,
      types: null,
      includeMatches: true,
    });
    expect(out).toEqual([]);
  });

  it('skips events for kids missing from kidsById', () => {
    const out = mergeKidCalendars(
      [{ kid_id: 99, from: 'x', to: 'y', events: [ev('2026-05-13', 'orphan')] }],
      new Map([[1, sam]]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out).toEqual([]);
  });
});
