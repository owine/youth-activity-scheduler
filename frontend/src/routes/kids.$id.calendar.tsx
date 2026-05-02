import { useState, useMemo } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import type { View } from 'react-big-calendar';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useKid, useKidCalendar } from '@/lib/queries';
import { KidTabs } from '@/components/layout/KidTabs';
import { CalendarView } from '@/components/calendar/CalendarView';
import { CalendarEventPopover } from '@/components/calendar/CalendarEventPopover';
import { rangeFor } from '@/lib/calendarRange';
import type { CalendarEvent } from '@/lib/types';

export const Route = createFileRoute('/kids/$id/calendar')({ component: KidCalendarPage });

function KidCalendarPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const kid = useKid(kidId);

  const [view, setView] = useState<View>('week');
  const [cursor, setCursor] = useState<Date>(new Date());
  const [includeMatches, setIncludeMatches] = useState(false);
  const { from, to } = useMemo(() => rangeFor(view, cursor), [view, cursor]);

  const calendar = useKidCalendar({ kidId, from, to, includeMatches });
  const [selected, setSelected] = useState<CalendarEvent | null>(null);

  if (kid.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kid.isError) {
    return <ErrorBanner message={(kid.error as Error).message} onRetry={() => kid.refetch()} />;
  }
  if (!kid.data) return null;

  return (
    <div>
      <h1 className="text-xl font-semibold mb-2">{kid.data.name}'s calendar</h1>
      <KidTabs kidId={kidId} />
      <div className="my-2 flex justify-end">
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeMatches}
            onChange={(e) => setIncludeMatches(e.target.checked)}
          />
          Show matches
        </label>
      </div>
      {calendar.isError && (
        <ErrorBanner
          message={(calendar.error as Error).message}
          onRetry={() => calendar.refetch()}
        />
      )}
      <CalendarView
        events={calendar.data?.events ?? []}
        view={view}
        onView={setView}
        date={cursor}
        onNavigate={setCursor}
        onSelectEvent={setSelected}
      />
      <CalendarEventPopover
        kidId={kidId}
        event={selected}
        open={selected !== null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
