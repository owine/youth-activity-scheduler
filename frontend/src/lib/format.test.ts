import { describe, expect, it } from 'vitest';
import { price, relDate } from './format';

describe('price', () => {
  it('returns empty for null', () => expect(price(null)).toBe(''));
  it('returns empty for negative', () => expect(price(-1)).toBe(''));
  it('returns Free for zero', () => expect(price(0)).toBe('Free'));
  it('formats positive', () => expect(price(12.5)).toBe('$12.50'));
});

describe('relDate', () => {
  const now = new Date('2026-04-24T12:00:00Z');
  it('Today', () => expect(relDate('2026-04-24T08:00:00Z', now)).toBe('Today'));
  it('Tomorrow', () => expect(relDate('2026-04-25T12:00:00Z', now)).toBe('Tomorrow'));
  it('in N days', () => expect(relDate('2026-04-28T12:00:00Z', now)).toBe('in 4 days'));
  it('weekday MMM d for ~3mo window', () => {
    const d = relDate('2026-05-15T12:00:00Z', now);
    expect(d).toMatch(/^\w{3} May 15$/);
  });
});
