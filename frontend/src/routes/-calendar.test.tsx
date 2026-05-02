import { vi } from 'vitest';

interface MockCalendarViewProps {
  events: Array<{ title: string }>;
}
interface MockFiltersProps {
  filters: { kidIds: number[] | null };
  onChange: (next: { kidIds: number[] | null }) => void;
  onClear: () => void;
}

vi.mock('@/components/calendar/CalendarView', () => ({
  CalendarView: ({ events }: MockCalendarViewProps) => (
    <div data-testid="calendar-view">
      {events.map((e, i) => (
        <div key={i}>{e.title}</div>
      ))}
    </div>
  ),
}));

vi.mock('@/components/calendar/CalendarEventPopover', () => ({
  CalendarEventPopover: () => null,
}));

vi.mock('@/components/calendar/CombinedCalendarFilters', () => ({
  CombinedCalendarFilters: ({ filters, onChange, onClear }: MockFiltersProps) => (
    <div data-testid="filters">
      <button onClick={() => onChange({ ...filters, kidIds: [1] })}>FilterKid1</button>
      <button onClick={onClear}>ClearFilters</button>
    </div>
  ),
}));

vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router',
  );
  return {
    ...actual,
    Link: ({
      to,
      children,
      ...props
    }: {
      to: string;
      children?: React.ReactNode;
    } & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    useNavigate: () => vi.fn(),
  };
});

import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { CalendarPage } from './calendar';

const sam = { id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true };
const lila = { id: 2, name: 'Lila', dob: '2017-08-12', interests: [], active: true };

const server = setupServer(
  http.get('/api/kids', () => HttpResponse.json([sam, lila])),
  http.get('/api/kids/1/calendar', () =>
    HttpResponse.json({
      kid_id: 1,
      from: '2026-05-10',
      to: '2026-05-16',
      events: [
        {
          id: 'enrollment:1:2026-05-13',
          kind: 'enrollment',
          date: '2026-05-13',
          time_start: '09:00:00',
          time_end: '10:00:00',
          all_day: false,
          title: 'T-Ball',
        },
      ],
    }),
  ),
  http.get('/api/kids/2/calendar', () =>
    HttpResponse.json({
      kid_id: 2,
      from: '2026-05-10',
      to: '2026-05-16',
      events: [
        {
          id: 'enrollment:2:2026-05-13',
          kind: 'enrollment',
          date: '2026-05-13',
          time_start: '14:00:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'Soccer',
        },
      ],
    }),
  ),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage(searchParams: Record<string, string> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CalendarPage searchParams={searchParams} />
    </QueryClientProvider>,
  );
}

describe('CalendarPage', () => {
  it('renders both kids events with prefixed titles', async () => {
    renderPage();
    expect(await screen.findByText(/Sam: T-Ball/)).toBeInTheDocument();
    expect(await screen.findByText(/Lila: Soccer/)).toBeInTheDocument();
  });

  it('renders empty state when no active kids', async () => {
    server.use(http.get('/api/kids', () => HttpResponse.json([])));
    renderPage();
    expect(await screen.findByText(/Add a kid/i)).toBeInTheDocument();
  });
});
