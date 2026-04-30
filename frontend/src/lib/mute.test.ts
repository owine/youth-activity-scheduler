import { describe, it, expect } from 'vitest';
import { FOREVER_SENTINEL, isMuted, muteUntilFromDuration } from './mute';

describe('muteUntilFromDuration', () => {
  it('returns the forever sentinel for "forever"', () => {
    expect(muteUntilFromDuration('forever')).toBe(FOREVER_SENTINEL);
  });

  it('returns now + 7 days for "7d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('7d', now)).toBe('2026-05-06T12:00:00.000Z');
  });

  it('returns now + 30 days for "30d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('30d', now)).toBe('2026-05-29T12:00:00.000Z');
  });

  it('returns now + 90 days for "90d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('90d', now)).toBe('2026-07-28T12:00:00.000Z');
  });
});

describe('isMuted', () => {
  it('returns false for null', () => {
    expect(isMuted(null)).toBe(false);
  });

  it('returns false for past timestamps', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted('2026-04-28T12:00:00Z', now)).toBe(false);
  });

  it('returns true for future timestamps', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted('2026-05-01T12:00:00Z', now)).toBe(true);
  });

  it('returns true for the forever sentinel', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted(FOREVER_SENTINEL, now)).toBe(true);
  });
});
