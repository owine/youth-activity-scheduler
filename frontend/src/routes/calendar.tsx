import { useMemo, useState } from 'react';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { useQueries } from '@tanstack/react-query';
import type { View } from 'react-big-calendar';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useKids } from '@/lib/queries';
import { api } from '@/lib/api';
import { CalendarView } from '@/components/calendar/CalendarView';
import { CalendarEventPopover } from '@/components/calendar/CalendarEventPopover';
import { CombinedCalendarFilters } from '@/components/calendar/CombinedCalendarFilters';
import { rangeFor } from '@/lib/calendarRange';
import { mergeKidCalendars } from '@/lib/combinedCalendar';
import { colorForKid } from '@/lib/calendarColors';
import type {
  CalendarEvent,
  CalendarEventKind,
  CombinedCalendarEvent,
  CombinedCalendarFilterState,
  KidCalendarResponse,
} from '@/lib/types';

type SearchParams = Record<string, string>;

export const Route = createFileRoute('/calendar')({
  component: CalendarPageRoute,
  validateSearch: (input: Record<string, unknown>): SearchParams => {
    const out: SearchParams = {};
    for (const [k, v] of Object.entries(input)) {
      if (typeof v === 'string') out[k] = v;
    }
    return out;
  },
});

function parseFilters(sp: SearchParams): CombinedCalendarFilterState {
  const kidIds = sp.kids
    ? sp.kids
        .split(',')
        .map((s) => Number(s))
        .filter((n) => Number.isFinite(n) && n > 0)
    : null;
  const types = sp.types
    ? (sp.types.split(',') as CalendarEventKind[]).filter((t): t is CalendarEventKind =>
        ['enrollment', 'unavailability', 'match'].includes(t),
      )
    : null;
  return {
    kidIds: kidIds && kidIds.length > 0 ? kidIds : null,
    types: types && types.length > 0 ? types : null,
    includeMatches: sp.include_matches === 'true',
  };
}

function filtersToParams(f: CombinedCalendarFilterState): SearchParams {
  const out: SearchParams = {};
  if (f.kidIds !== null) out.kids = f.kidIds.join(',');
  if (f.types !== null) out.types = f.types.join(',');
  if (f.includeMatches) out.include_matches = 'true';
  return out;
}

export function CalendarPage({ searchParams }: { searchParams: SearchParams }) {
  const navigate = useNavigate();
  const kids = useKids();

  const view: View = searchParams.view === 'month' ? 'month' : 'week';
  const cursor = useMemo(
    () => (searchParams.date ? new Date(`${searchParams.date}T00:00:00`) : new Date()),
    [searchParams.date],
  );
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const { from, to } = useMemo(() => rangeFor(view, cursor), [view, cursor]);
  const activeKids = useMemo(() => kids.data?.filter((k) => k.active) ?? [], [kids.data]);

  const queries = useQueries({
    queries: activeKids.map((k) => ({
      queryKey: ['kid-calendar', k.id, from, to, filters.includeMatches],
      queryFn: () =>
        api.get<KidCalendarResponse>(
          `/api/kids/${k.id}/calendar?from=${from}&to=${to}${filters.includeMatches ? '&include_matches=true' : ''}`,
        ),
      enabled: kids.isSuccess,
    })),
  });

  const kidsById = useMemo(() => new Map(activeKids.map((k) => [k.id, k])), [activeKids]);
  const [selected, setSelected] = useState<CombinedCalendarEvent | null>(null);

  const updateSearch = (next: Partial<SearchParams>) => {
    const merged: SearchParams = { ...searchParams };
    for (const [k, v] of Object.entries(next)) {
      if (v === undefined) delete merged[k];
      else merged[k] = v;
    }
    navigate({ to: '/calendar', search: merged });
  };

  if (kids.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kids.isError) {
    return <ErrorBanner message={(kids.error as Error).message} onRetry={() => kids.refetch()} />;
  }

  if (activeKids.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p className="mb-3">Add a kid to see a combined calendar.</p>
        <Link to="/kids/new" className="underline">
          Add kid
        </Link>
      </div>
    );
  }

  const allLoaded = queries.every((q) => q.isSuccess);
  const failedKidNames = queries
    .map((q, i) => (q.isError ? activeKids[i]!.name : null))
    .filter((n): n is string => n !== null);

  if (!allLoaded && queries.some((q) => q.isLoading)) {
    return <Skeleton className="h-96 w-full" />;
  }

  const responses: KidCalendarResponse[] = queries
    .map((q) => q.data)
    .filter((r): r is KidCalendarResponse => r !== undefined);
  const events = mergeKidCalendars(responses, kidsById, filters);

  const visibleKidCount = filters.kidIds === null ? activeKids.length : filters.kidIds.length;
  if (visibleKidCount === 0) {
    return (
      <div>
        <h1 className="text-xl font-semibold mb-2">Combined calendar</h1>
        <CombinedCalendarFilters
          kids={activeKids}
          filters={filters}
          onChange={(next) => updateSearch(filtersToParams(next))}
          onClear={() => navigate({ to: '/calendar', search: {} as SearchParams })}
        />
        <p className="mt-8 text-center text-muted-foreground">No kids selected.</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-2">Combined calendar</h1>
      {failedKidNames.length > 0 && (
        <ErrorBanner
          message={`Failed to load: ${failedKidNames.join(', ')}`}
          onRetry={() => queries.forEach((q) => q.isError && q.refetch())}
        />
      )}
      <div className="my-2">
        <CombinedCalendarFilters
          kids={activeKids}
          filters={filters}
          onChange={(next) => updateSearch(filtersToParams(next))}
          onClear={() => navigate({ to: '/calendar', search: {} as SearchParams })}
        />
      </div>
      <CalendarView
        events={events}
        view={view}
        onView={(v) => updateSearch({ view: v })}
        date={cursor}
        onNavigate={(d) => updateSearch({ date: d.toISOString().slice(0, 10) })}
        onSelectEvent={(e: CalendarEvent) => setSelected(e as CombinedCalendarEvent)}
        eventStyle={(e) => {
          const cev = e as CombinedCalendarEvent;
          const c = colorForKid(cev.kid_id);
          return { className: c.bg, style: { color: 'white' } };
        }}
      />
      <CalendarEventPopover
        event={selected}
        kidId={selected?.kid_id ?? 0}
        open={selected !== null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

function CalendarPageRoute() {
  const search = Route.useSearch();
  return <CalendarPage searchParams={search} />;
}
