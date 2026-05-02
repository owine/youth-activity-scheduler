import type {
  CalendarEvent,
  CombinedCalendarEvent,
  CombinedCalendarFilterState,
  KidBrief,
  KidCalendarResponse,
} from './types';

function timeKey(e: CalendarEvent): string {
  return `${e.date}T${e.time_start ?? '00:00:00'}`;
}

export function mergeKidCalendars(
  responses: readonly KidCalendarResponse[],
  kidsById: ReadonlyMap<number, KidBrief>,
  filters: CombinedCalendarFilterState,
): CombinedCalendarEvent[] {
  const out: CombinedCalendarEvent[] = [];
  for (const resp of responses) {
    const kid = kidsById.get(resp.kid_id);
    if (!kid) continue;
    if (filters.kidIds !== null && !filters.kidIds.includes(kid.id)) continue;
    for (const event of resp.events) {
      if (!filters.includeMatches && event.kind === 'match') continue;
      if (filters.types !== null && !filters.types.includes(event.kind)) continue;
      out.push({
        ...event,
        kid_id: kid.id,
        title: `${kid.name}: ${event.title}`,
      });
    }
  }
  out.sort((a, b) => {
    const ak = timeKey(a);
    const bk = timeKey(b);
    if (ak < bk) return -1;
    if (ak > bk) return 1;
    return 0;
  });
  return out;
}
