import { Calendar, dateFnsLocalizer, Views, type View } from 'react-big-calendar';
import { format, parse, startOfWeek, getDay } from 'date-fns';
import { enUS } from 'date-fns/locale';
import type { CalendarEvent, CalendarEventKind } from '@/lib/types';
import 'react-big-calendar/lib/css/react-big-calendar.css';
import './calendar-overrides.css';

const locales = { 'en-US': enUS };
const localizer = dateFnsLocalizer({ format, parse, startOfWeek, getDay, locales });

interface RbcEvent {
  title: string;
  start: Date;
  end: Date;
  allDay: boolean;
  resource: CalendarEvent;
}

function parseDateParts(dateStr: string): [number, number, number] {
  const parts = dateStr.split('-').map(Number);
  return [parts[0] ?? 0, parts[1] ?? 1, parts[2] ?? 1];
}

function parseTimeParts(timeStr: string): [number, number] {
  const parts = timeStr.split(':').map(Number);
  return [parts[0] ?? 0, parts[1] ?? 0];
}

// Exhaustive map: TypeScript will flag any future CalendarEventKind member
// that's missing here. Avoids the silent fall-through a chained ternary had.
const KIND_CLASS: Record<CalendarEventKind, string> = {
  enrollment: 'rbc-event-enrollment',
  unavailability: 'rbc-event-unavailability',
  match: 'rbc-event-match',
  holiday: 'rbc-event-holiday',
};

function toRbc(e: CalendarEvent): RbcEvent {
  const [y, m, d] = parseDateParts(e.date);
  if (e.all_day) {
    const start = new Date(y, m - 1, d, 0, 0, 0);
    const end = new Date(y, m - 1, d + 1, 0, 0, 0);
    return { title: e.title, start, end, allDay: true, resource: e };
  }
  const [sh, sm] = parseTimeParts(e.time_start ?? '00:00:00');
  const [eh, em] = parseTimeParts(e.time_end ?? '23:59:59');
  const start = new Date(y, m - 1, d, sh, sm, 0);
  const end = new Date(y, m - 1, d, eh, em, 0);
  return { title: e.title, start, end, allDay: false, resource: e };
}

export function CalendarView({
  events,
  view,
  onView,
  date,
  onNavigate,
  onSelectEvent,
  eventStyle,
}: {
  events: CalendarEvent[];
  view: View;
  onView: (v: View) => void;
  date: Date;
  onNavigate: (d: Date) => void;
  onSelectEvent: (e: CalendarEvent) => void;
  /** Optional per-event style override. The kind-based className
   *  (rbc-event-enrollment etc.) is preserved; the override's className
   *  is concatenated and `style` is shallow-merged on top. */
  eventStyle?: (event: CalendarEvent) => {
    className?: string;
    style?: React.CSSProperties;
  };
}) {
  const rbcEvents = events.map(toRbc);
  return (
    <div className="h-[70vh]">
      <Calendar
        localizer={localizer}
        events={rbcEvents}
        views={[Views.WEEK, Views.MONTH]}
        view={view}
        onView={onView}
        date={date}
        onNavigate={onNavigate}
        min={new Date(0, 0, 0, 6, 0, 0)}
        max={new Date(0, 0, 0, 22, 0, 0)}
        onSelectEvent={(rbc) => onSelectEvent((rbc as RbcEvent).resource)}
        eventPropGetter={(rbc) => {
          const ev = (rbc as RbcEvent).resource;
          const kindClass = KIND_CLASS[ev.kind];
          // Watchlist matches get an extra modifier class on top of the
          // base match class so the user can recognize personally-flagged
          // hits at a glance (gold ring vs the default dashed border).
          const watchlistClass =
            ev.kind === 'match' && ev.watchlist_hit ? 'rbc-event-watchlist' : '';
          const override = eventStyle?.(ev);
          return {
            className: [kindClass, watchlistClass, override?.className].filter(Boolean).join(' '),
            ...(override?.style ? { style: override.style } : {}),
          };
        }}
      />
    </div>
  );
}
