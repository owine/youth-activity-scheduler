import { describe, it, expect } from 'vitest';
import { CALENDAR_KID_COLORS, colorForKid } from './calendarColors';

describe('colorForKid', () => {
  it('returns same color for same kid id', () => {
    expect(colorForKid(1)).toEqual(colorForKid(1));
  });

  it('returns different colors for different ids within palette length', () => {
    const colors = new Set<string>();
    for (let i = 0; i < CALENDAR_KID_COLORS.length; i++) {
      colors.add(colorForKid(i + 1).bg);
    }
    expect(colors.size).toBe(CALENDAR_KID_COLORS.length);
  });

  it('wraps around palette length', () => {
    const len = CALENDAR_KID_COLORS.length;
    expect(colorForKid(1)).toEqual(colorForKid(1 + len));
  });

  it('palette has at least 8 colors', () => {
    expect(CALENDAR_KID_COLORS.length).toBeGreaterThanOrEqual(8);
  });

  it('each entry has bg and text class strings and hex', () => {
    for (const c of CALENDAR_KID_COLORS) {
      expect(c.bg).toMatch(/^bg-/);
      expect(c.text).toMatch(/^text-/);
      expect(c.hex).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});
