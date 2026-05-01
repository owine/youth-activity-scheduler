import { useEffect, useRef, useMemo, useState } from 'react';
import { useAllMatches, useHousehold, useKids } from '@/lib/queries';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { MatchDetailDrawer } from '@/components/matches/MatchDetailDrawer';
import { FilterBar } from './FilterBar';
import { OfferingRow } from './OfferingRow';
import {
  groupByOffering,
  applyFilters,
  sortOfferingRows,
  defaultFilterState,
} from '@/lib/offeringsFilters';
import type { FilterState, Match } from '@/lib/types';

const STORAGE_KEY = 'yas:offerings-filter-v1';
const PROGRAM_TYPES_BUILTIN = [
  // mirror of yas.db.models._types.ProgramType minus 'unknown'
  'soccer',
  'baseball',
  'softball',
  'basketball',
  'hockey',
  'football',
  'swim',
  'martial_arts',
  'gymnastics',
  'dance',
  'gym',
  'art',
  'music',
  'stem',
  'academic',
  'multisport',
  'outdoor',
  'camp_general',
];

export function OfferingsBrowserPage() {
  const kids = useKids();
  const household = useHousehold();
  const allKidIds = useMemo(() => kids.data?.map((k) => k.id) ?? [], [kids.data]);

  const initializeRef = useRef(false);
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [selected, setSelected] = useState<Match | null>(null);

  // First mount: hydrate from localStorage or use defaults.
  useEffect(() => {
    if (initializeRef.current) return;
    if (kids.data === undefined) return;
    initializeRef.current = true;
    const raw = localStorage.getItem(STORAGE_KEY);
    let parsed: FilterState | null = null;
    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch {
        // fall through
      }
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters(parsed ?? defaultFilterState(allKidIds));
  }, [allKidIds, kids.data]);

  // Persist filter state to localStorage when it changes.
  useEffect(() => {
    if (filters === null) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
  }, [filters]);

  const matchesQuery = useAllMatches({ minScore: filters?.minScore ?? 0.6 });

  if (kids.isLoading || household.isLoading || matchesQuery.isLoading || filters === null) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (kids.isError || matchesQuery.isError) {
    return (
      <ErrorBanner message="Failed to load offerings" onRetry={() => matchesQuery.refetch()} />
    );
  }
  if ((kids.data?.length ?? 0) === 0) {
    return <EmptyState>Add a kid first to see offerings.</EmptyState>;
  }
  if ((matchesQuery.data?.length ?? 0) === 0) {
    return (
      <EmptyState>
        No matches yet — pages need to be crawled before offerings appear here.
      </EmptyState>
    );
  }

  const matches = matchesQuery.data ?? [];
  const truncated = matches.length === 500;
  const kidsById = new Map(kids.data!.map((k) => [k.id, k]));

  const grouped = groupByOffering(matches);
  const filtered = applyFilters(grouped, filters, household.data);
  const sorted = sortOfferingRows(filtered, filters.sort);

  const now = new Date();

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Offerings</h1>
      <FilterBar
        value={filters}
        onChange={setFilters}
        kids={kids.data ?? []}
        programTypeOptions={PROGRAM_TYPES_BUILTIN}
      />
      {truncated && (
        <div className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
          Showing 500 of 500+ matches — narrow your filters to see more.
        </div>
      )}
      {sorted.length === 0 ? (
        <EmptyState>
          No offerings match your filters.{' '}
          <button
            type="button"
            className="underline"
            onClick={() => setFilters(defaultFilterState(allKidIds))}
          >
            Clear filters
          </button>
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {sorted.map((row) => (
            <li key={row.offering.id}>
              <OfferingRow row={row} kidsById={kidsById} now={now} onSelect={setSelected} />
            </li>
          ))}
        </ul>
      )}
      <MatchDetailDrawer
        match={selected}
        open={selected !== null}
        onOpenChange={(o) => {
          if (!o) setSelected(null);
        }}
      />
    </div>
  );
}
