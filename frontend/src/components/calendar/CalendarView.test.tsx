import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CalendarView } from './CalendarView';
import type { CalendarEvent } from '@/lib/types';

const events: CalendarEvent[] = [
  {
    id: 'enrollment:1:2026-04-29',
    kind: 'enrollment',
    date: '2026-04-29',
    time_start: '16:00:00',
    time_end: '17:00:00',
    all_day: false,
    title: 'T-Ball',
    enrollment_id: 1,
    offering_id: 7,
    status: 'enrolled',
  },
];

describe('CalendarView', () => {
  it('renders an event title in the grid', () => {
    render(
      <CalendarView
        events={events}
        view="week"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
      />,
    );
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
  });

  it('calls onSelectEvent when an event is clicked', async () => {
    const onSelectEvent = vi.fn();
    render(
      <CalendarView
        events={events}
        view="week"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={onSelectEvent}
      />,
    );
    await userEvent.click(screen.getByText(/T-Ball/i));
    expect(onSelectEvent).toHaveBeenCalledTimes(1);
    expect((onSelectEvent.mock.calls[0] as [CalendarEvent])[0].id).toBe('enrollment:1:2026-04-29');
  });

  it('renders the same events in month view', () => {
    render(
      <CalendarView
        events={events}
        view="month"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
      />,
    );
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
  });
});
