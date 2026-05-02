import { describe, it, expect } from 'vitest';
import { rangeFor, BUFFER_DAYS } from './calendarRange';

describe('rangeFor', () => {
  it('returns week range with 3-day buffer on either side', () => {
    // Wed May 13 2026; week starts Sun May 10
    const { from, to } = rangeFor('week', new Date(2026, 4, 13));
    expect(from).toBe('2026-05-07'); // May 10 - 3
    expect(to).toBe('2026-05-20'); // May 10 + 7 + 3
  });

  it('returns month range covering surrounding weeks plus buffer', () => {
    const { from, to } = rangeFor('month', new Date(2026, 4, 13));
    // May 1 2026 is a Friday → week starts Sun Apr 26 → -3 buffer = Apr 23
    // May 31 + 7 + 3 = June 10
    expect(from).toBe('2026-04-23');
    expect(to).toBe('2026-06-10');
  });

  it('exposes BUFFER_DAYS = 3', () => {
    expect(BUFFER_DAYS).toBe(3);
  });
});
