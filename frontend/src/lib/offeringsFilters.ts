import type { Chip, FilterState, Household, KidBrief, Match, OfferingRow, SortKey } from './types';

// Earth radius in miles (haversine).
const R_MILES = 3958.8;

function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_MILES * Math.asin(Math.sqrt(a));
}

export function defaultFilterState(allKidIds: number[]): FilterState {
  return {
    selectedKidIds: [...allKidIds],
    minScore: 0.6,
    sort: 'best_score',
    hideMuted: true,
    programTypes: [],
    days: [],
    regTiming: 'any',
    timeOfDayMin: null,
    timeOfDayMax: null,
    maxDistanceMi: null,
    ageMin: null,
    ageMax: null,
    watchlistOnly: false,
    moreFiltersOpen: false,
  };
}

export function groupByOffering(matches: Match[]): OfferingRow[] {
  const byId = new Map<number, OfferingRow>();
  for (const m of matches) {
    const existing = byId.get(m.offering_id);
    if (existing) {
      existing.matches.push(m);
    } else {
      byId.set(m.offering_id, { offering: m.offering, matches: [m] });
    }
  }
  for (const row of byId.values()) {
    row.matches.sort((a, b) => b.score - a.score);
  }
  return [...byId.values()];
}

export function applyFilters(
  rows: OfferingRow[],
  f: FilterState,
  household: Household | undefined,
  now: Date = new Date(),
): OfferingRow[] {
  const selectedKids = new Set(f.selectedKidIds);
  return rows
    .map((row) => ({
      ...row,
      matches: row.matches.filter((m) => selectedKids.has(m.kid_id)),
    }))
    .filter((row) => row.matches.length > 0)
    .filter((row) => {
      const o = row.offering;
      // hideMuted
      if (f.hideMuted && o.muted_until && new Date(o.muted_until) > now) return false;
      // programTypes
      if (f.programTypes.length > 0 && !f.programTypes.includes(o.program_type)) return false;
      // days AND-match
      if (f.days.length > 0) {
        const offeringDays = new Set(
          (o.days_of_week ?? []).map((d) => d.toLowerCase().slice(0, 3)),
        );
        if (!f.days.every((d) => offeringDays.has(d))) return false;
      }
      // time-of-day range: offering must overlap with the filter window
      if (f.timeOfDayMin && o.time_end && o.time_end.slice(0, 5) < f.timeOfDayMin) return false;
      if (f.timeOfDayMax && o.time_start && o.time_start.slice(0, 5) > f.timeOfDayMax) return false;
      // reg timing
      if (f.regTiming !== 'any') {
        const ro = o.registration_opens_at ? new Date(o.registration_opens_at) : null;
        const ed = o.end_date ? new Date(o.end_date) : null;
        const sd = o.start_date ? new Date(o.start_date) : null;
        const inWeek = ro && ro >= now && ro <= new Date(now.getTime() + 7 * 86400000);
        const isOpen = ro && ro <= now && (!ed || ed >= now);
        const isClosed = (ed && ed < now) || (sd && sd < now && !ro);
        if (f.regTiming === 'opens_this_week' && !inWeek) return false;
        if (f.regTiming === 'open_now' && !isOpen) return false;
        if (f.regTiming === 'closed' && !isClosed) return false;
      }
      // distance
      if (
        f.maxDistanceMi !== null &&
        household?.home_lat != null &&
        household.home_lon != null &&
        o.location_lat != null &&
        o.location_lon != null
      ) {
        const miles = haversine(
          household.home_lat,
          household.home_lon,
          o.location_lat,
          o.location_lon,
        );
        if (miles > f.maxDistanceMi) return false;
      }
      // age range overlap
      if (f.ageMin !== null && o.age_max !== null && o.age_max < f.ageMin) return false;
      if (f.ageMax !== null && o.age_min !== null && o.age_min > f.ageMax) return false;
      // watchlist only
      if (f.watchlistOnly && !row.matches.some((m) => isWatchlistHit(m))) return false;
      return true;
    });
}

function isWatchlistHit(m: Match): boolean {
  const wh = (m.reasons as { watchlist_hit?: unknown })?.watchlist_hit;
  return wh != null && wh !== false;
}

export function sortOfferingRows(rows: OfferingRow[], sort: SortKey): OfferingRow[] {
  const cmpId = (a: OfferingRow, b: OfferingRow) => b.offering.id - a.offering.id;
  if (sort === 'best_score') {
    return [...rows].sort((a, b) => {
      const ds = (b.matches[0]?.score ?? 0) - (a.matches[0]?.score ?? 0);
      return ds !== 0 ? ds : cmpId(a, b);
    });
  }
  if (sort === 'soonest_start') {
    return [...rows].sort((a, b) => {
      const av = a.offering.start_date ?? '￿';
      const bv = b.offering.start_date ?? '￿';
      const d = av.localeCompare(bv);
      return d !== 0 ? d : cmpId(a, b);
    });
  }
  // soonest_reg
  return [...rows].sort((a, b) => {
    const av = a.offering.registration_opens_at ?? '￿';
    const bv = b.offering.registration_opens_at ?? '￿';
    const d = av.localeCompare(bv);
    return d !== 0 ? d : cmpId(a, b);
  });
}

export function chipsForOffering(
  row: OfferingRow,
  kidsById: Map<number, KidBrief>,
  now: Date,
): Chip[] {
  const chips: Chip[] = [];
  // 1. Watchlist
  if (row.matches.some((m) => isWatchlistHit(m))) {
    chips.push({
      kind: 'watchlist',
      label: '⭐ Watchlist',
      className: 'bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200',
    });
  }
  // 2. Top match
  if ((row.matches[0]?.score ?? 0) >= 0.85) {
    chips.push({
      kind: 'top_match',
      label: '🎯 Top match',
      className: 'bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-200',
    });
  }
  // 3. Opens this week
  const ro = row.offering.registration_opens_at;
  if (ro) {
    const dt = new Date(ro);
    const week = new Date(now.getTime() + 7 * 86400000);
    if (dt >= now && dt <= week) {
      chips.push({
        kind: 'opens_this_week',
        label: '🔥 Opens this week',
        className: 'bg-orange-100 text-orange-900 dark:bg-orange-900/30 dark:text-orange-200',
      });
    }
  }
  // 4. Near home (normalized signal)
  if (
    row.matches.some((m) => {
      const sb = (m.reasons as { score_breakdown?: { distance?: number } })?.score_breakdown;
      return typeof sb?.distance === 'number' && sb.distance >= 0.7;
    })
  ) {
    chips.push({
      kind: 'near_home',
      label: '📍 Near home',
      className: 'bg-blue-100 text-blue-900 dark:bg-blue-900/30 dark:text-blue-200',
    });
  }
  // 5. In interests
  const inInterests = row.matches.some((m) => {
    const kid = kidsById.get(m.kid_id);
    return kid?.interests?.includes(row.offering.program_type) ?? false;
  });
  if (inInterests) {
    chips.push({
      kind: 'in_interests',
      label: '🏷 In interests',
      className: 'bg-purple-100 text-purple-900 dark:bg-purple-900/30 dark:text-purple-200',
    });
  }
  // 6. Drive time (matcher computed routed driving minutes; surface them
  // when present so the user sees "21 min drive" alongside the other chips)
  const driveMinutesValues = row.matches
    .map((m) => (m.reasons as { drive_minutes?: unknown }).drive_minutes)
    .filter((v): v is number => typeof v === 'number');
  if (driveMinutesValues.length > 0) {
    const min = Math.round(Math.min(...driveMinutesValues));
    chips.push({
      kind: 'drive_time',
      label: `🚗 ${min} min drive`,
      className: 'bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-200',
    });
  }
  // 7. Tight (soft conflict — matcher flagged a near-miss against an
  // unavailability block, e.g., school ends 3pm and offering starts 3:10pm)
  const tight = row.matches.some(
    (m) =>
      Array.isArray((m.reasons as { soft_conflicts?: unknown }).soft_conflicts) &&
      ((m.reasons as { soft_conflicts: unknown[] }).soft_conflicts?.length ?? 0) > 0,
  );
  if (tight) {
    chips.push({
      kind: 'tight',
      label: '⚠ Tight',
      className: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-900/30 dark:text-yellow-200',
    });
  }
  return chips.slice(0, 3);
}
