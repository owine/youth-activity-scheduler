export const FOREVER_SENTINEL = '3000-01-01T00:00:00.000Z';

export type MuteDuration = '7d' | '30d' | '90d' | 'forever';

const DAYS: Record<Exclude<MuteDuration, 'forever'>, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};

export function muteUntilFromDuration(
  duration: MuteDuration,
  now: Date = new Date(),
): string {
  if (duration === 'forever') return FOREVER_SENTINEL;
  const out = new Date(now);
  out.setDate(out.getDate() + DAYS[duration]);
  return out.toISOString();
}

export function isMuted(
  mutedUntil: string | null,
  now: Date = new Date(),
): boolean {
  if (mutedUntil == null) return false;
  return new Date(mutedUntil) > now;
}
