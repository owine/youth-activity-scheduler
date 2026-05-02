export interface KidColor {
  bg: string;
  text: string;
  hex: string;
}

export const CALENDAR_KID_COLORS: readonly KidColor[] = [
  { bg: 'bg-blue-500', text: 'text-white', hex: '#3b82f6' },
  { bg: 'bg-amber-500', text: 'text-white', hex: '#f59e0b' },
  { bg: 'bg-emerald-500', text: 'text-white', hex: '#10b981' },
  { bg: 'bg-violet-500', text: 'text-white', hex: '#8b5cf6' },
  { bg: 'bg-rose-500', text: 'text-white', hex: '#f43f5e' },
  { bg: 'bg-teal-500', text: 'text-white', hex: '#14b8a6' },
  { bg: 'bg-orange-500', text: 'text-white', hex: '#f97316' },
  { bg: 'bg-cyan-600', text: 'text-white', hex: '#0891b2' },
] as const;

export function colorForKid(kidId: number): KidColor {
  const len = CALENDAR_KID_COLORS.length;
  const idx = (((kidId - 1) % len) + len) % len;
  return CALENDAR_KID_COLORS[idx]!;
}
