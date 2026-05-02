import type { Match } from './types';

export type Urgency = 'opens-this-week' | 'starting-soon' | 'later';

export function urgencyOf(m: Match, now = new Date()): Urgency {
  const opens = m.offering.registration_opens_at
    ? new Date(m.offering.registration_opens_at)
    : null;
  if (opens) {
    const days = (opens.getTime() - now.getTime()) / 86_400_000;
    if (days >= 0 && days <= 7) return 'opens-this-week';
  }
  const start = m.offering.start_date ? new Date(m.offering.start_date) : null;
  if (start) {
    const days = (start.getTime() - now.getTime()) / 86_400_000;
    if (days >= 0 && days <= 14) return 'starting-soon';
  }
  return 'later';
}

export function groupByUrgency(matches: Match[], now = new Date()): Record<Urgency, Match[]> {
  const out: Record<Urgency, Match[]> = { 'opens-this-week': [], 'starting-soon': [], later: [] };
  for (const m of matches) out[urgencyOf(m, now)].push(m);
  return out;
}
