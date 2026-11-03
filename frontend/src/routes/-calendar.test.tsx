import { vi } from 'vitest';

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }));

interface MockCalendarViewProps {
  events: Array<{ title: string }>;
  onNavigate: (d: Date) => void;
}
interface MockFiltersProps {
  filters: { kidIds: number[] | null };
  onChange: (next: { kidIds: number[] | null }) => void;
  onClear: () => void;
}

vi.mock('@/components/calendar/CalendarView', () => ({
  CalendarView: ({ events, onNavigate }: MockCalendarViewProps) => (
    <div data-testid="calendar-view">
      {events.map((e, i) => (
        <div key={i}>{e.title}</div>
      ))}
      {/* react-big-calendar keeps the cursor's time of day when it navigates,
          so an evening "Today" cursor arrives as a late-evening local Date. */}
      <button onClick={() => onNavigate(new Date(2026, 10, 2, 21, 30))}>NavigateEvening</button>
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
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router');
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
    useNavigate: () => navigateMock,
  };
});

import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

function renderPage(
  searchParams: Record<string, string> = {},
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
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

  it('stores the local calendar date when navigating in the evening', async () => {
    navigateMock.mockClear();
    renderPage();
    await screen.findByText(/Sam: T-Ball/);
    await userEvent.click(screen.getByRole('button', { name: 'NavigateEvening' }));
    expect(navigateMock).toHaveBeenCalledWith(
      expect.objectContaining({ search: expect.objectContaining({ date: '2026-11-02' }) }),
    );
  });

  it('refetches a kid when the per-kid calendar key is invalidated', async () => {
    // Enroll / cancel / mute / delete-block invalidate ['kids', kidId, 'calendar'],
    // so the combined view must share that key shape to see their effects.
    let samFetches = 0;
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/kids/1/calendar') samFetches += 1;
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage({}, qc);
    await screen.findByText(/Sam: T-Ball/);
    const before = samFetches;
    await qc.invalidateQueries({ queryKey: ['kids', 1, 'calendar'] });
    await waitFor(() => expect(samFetches).toBeGreaterThan(before));
    server.events.removeAllListeners();
  });
});
