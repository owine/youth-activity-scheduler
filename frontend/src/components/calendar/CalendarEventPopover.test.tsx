import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarEventPopover } from './CalendarEventPopover';
import type { CalendarEvent } from '@/lib/types';

const enrollment: CalendarEvent = {
  id: 'enrollment:42:2026-04-29',
  kind: 'enrollment',
  date: '2026-04-29',
  time_start: '16:00:00',
  time_end: '17:00:00',
  all_day: false,
  title: 'T-Ball',
  enrollment_id: 42,
  offering_id: 7,
  status: 'enrolled',
};

const enrollmentLinkedBlock: CalendarEvent = {
  id: 'unavailability:21:2026-04-29',
  kind: 'unavailability',
  date: '2026-04-29',
  time_start: '16:00:00',
  time_end: '17:00:00',
  all_day: false,
  title: 'T-Ball',
  block_id: 21,
  source: 'enrollment',
  from_enrollment_id: 42,
};

const standaloneBlock: CalendarEvent = {
  id: 'unavailability:20:2026-04-29',
  kind: 'unavailability',
  date: '2026-04-29',
  time_start: '08:30:00',
  time_end: '15:00:00',
  all_day: false,
  title: 'School',
  block_id: 20,
  source: 'school',
  from_enrollment_id: null,
};

function renderPopover(event: CalendarEvent | null, onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CalendarEventPopover kidId={1} event={event} open={event !== null} onClose={onClose} />
    </QueryClientProvider>,
  );
}

describe('CalendarEventPopover', () => {
  it('renders enrollment details + Cancel enrollment button', () => {
    renderPopover(enrollment);
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel enrollment/i })).toBeInTheDocument();
  });

  it('renders standalone block details + Delete block button', () => {
    renderPopover(standaloneBlock);
    expect(screen.getByText(/School/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete block/i })).toBeInTheDocument();
  });

  it('suppresses Delete on enrollment-linked blocks and shows hint', () => {
    renderPopover(enrollmentLinkedBlock);
    expect(screen.queryByRole('button', { name: /delete block/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cancel the enrollment/i)).toBeInTheDocument();
  });

  it('calls onClose after a successful Cancel enrollment', async () => {
    const onClose = vi.fn();
    renderPopover(enrollment, onClose);
    await userEvent.click(screen.getByRole('button', { name: /cancel enrollment/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
