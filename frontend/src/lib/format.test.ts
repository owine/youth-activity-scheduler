import { describe, expect, it } from 'vitest';
import { price, relDate } from './format';

describe('price', () => {
  it('returns empty for null', () => expect(price(null)).toBe(''));
  it('returns empty for negative', () => expect(price(-1)).toBe(''));
  it('returns Free for zero', () => expect(price(0)).toBe('Free'));
  it('formats positive', () => expect(price(12.5)).toBe('$12.50'));
});

describe('relDate', () => {
  // Calendar days are local, as they are for the user, so the fixtures are
  // local wall-clock times too: offset-less ISO strings parse as local time.
  // Instants pinned to UTC ("...Z") land on another local day in far-off zones.
  const now = new Date(2026, 3, 24, 12); // Fri 2026-04-24 12:00 local
  it('Today', () => expect(relDate('2026-04-24T08:00:00', now)).toBe('Today'));
  it('Tomorrow', () => expect(relDate('2026-04-25T12:00:00', now)).toBe('Tomorrow'));
  it('in N days', () => expect(relDate(new Date(2026, 3, 28, 12), now)).toBe('in 4 days'));
  it('weekday MMM d for ~3mo window', () => {
    expect(relDate('2026-05-15T12:00:00', now)).toBe('Fri May 15');
  });
});
