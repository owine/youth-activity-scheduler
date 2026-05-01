import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { EnrollmentEditSheet } from './EnrollmentEditSheet';
import type { Enrollment, OfferingSummary } from '@/lib/types';

const makeOffering = (over: Partial<OfferingSummary> = {}): OfferingSummary => ({
  id: 1,
  name: 'Soccer Camp',
  program_type: 'soccer',
  age_min: 5,
  age_max: 12,
  start_date: '2026-06-15',
  end_date: '2026-08-31',
  days_of_week: ['mon', 'wed', 'fri'],
  time_start: '17:00:00',
  time_end: '18:00:00',
  price_cents: 15000,
  registration_url: null,
  site_id: 1,
  registration_opens_at: '2026-05-15T00:00:00Z',
  site_name: 'Parks & Rec',
  muted_until: null,
  location_lat: null,
  location_lon: null,
  ...over,
});

const makeEnrollment = (over: Partial<Enrollment> = {}): Enrollment => ({
  id: 7,
  kid_id: 1,
  offering_id: 1,
  status: 'interested',
  enrolled_at: null,
  notes: null,
  created_at: '2026-05-01T00:00:00Z',
  offering: makeOffering(),
  ...over,
});

function renderWithQueryClient(component: React.ReactNode, qc: QueryClient = new QueryClient()) {
  return render(<QueryClientProvider client={qc}>{component}</QueryClientProvider>);
}

describe('EnrollmentEditSheet', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-05-01T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('pre-populates from enrollment data (notes textarea + enrolled_at date input)', async () => {
    const enrollment = makeEnrollment({
      notes: 'Already started but catching up',
      enrolled_at: '2026-04-25T00:00:00Z',
    });

    renderWithQueryClient(
      <EnrollmentEditSheet enrollment={enrollment} kidId={1} onClose={() => {}} />,
      new QueryClient(),
    );

    // Check that sheet title is shown (indicates sheet is open)
    expect(screen.getByText('Edit enrollment')).toBeInTheDocument();

    // Verify notes textarea has the current value
    const notesInput = screen.getByRole('textbox', { name: /Notes/i });
    expect(notesInput).toHaveValue('Already started but catching up');

    // Verify enrolled_at date input has the current value (YYYY-MM-DD format)
    const dateInput = document.querySelector('input[id="enrolled_at"]') as HTMLInputElement;
    expect(dateInput).toHaveValue('2026-04-25');
  });

  it('Save click PATCHes {notes, enrolled_at} (status NOT in payload)', async () => {
    let capturedBody: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/enrollments/:id', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: 7,
          kid_id: 1,
          offering_id: 1,
          status: 'interested',
          enrolled_at: capturedBody.enrolled_at ?? null,
          notes: capturedBody.notes ?? null,
          created_at: '2026-05-01T00:00:00Z',
          offering: makeOffering(),
        });
      }),
    );

    const onClose = vi.fn();
    const enrollment = makeEnrollment();
    const qc = new QueryClient();
    qc.setQueryData(['kids', 1, 'enrollments'], [enrollment]);

    renderWithQueryClient(
      <EnrollmentEditSheet enrollment={enrollment} kidId={1} onClose={onClose} />,
      qc,
    );

    // Modify notes and enrolled_at
    const notesInput = screen.getByRole('textbox', { name: /Notes/i });
    await userEvent.clear(notesInput);
    await userEvent.type(notesInput, 'Updated notes');

    const dateInput = document.querySelector('input[id="enrolled_at"]') as HTMLInputElement;
    await userEvent.clear(dateInput);
    await userEvent.type(dateInput, '2026-05-10');

    // Click Save
    const saveButton = screen.getByRole('button', { name: /Save/i });
    await userEvent.click(saveButton);

    // Verify PATCH body only contains notes and enrolled_at (no status)
    await waitFor(() => {
      expect(capturedBody).toEqual({
        notes: 'Updated notes',
        enrolled_at: '2026-05-10T00:00:00Z',
      });
    });

    // Verify onClose was called
    expect(onClose).toHaveBeenCalled();
  });

  it('Cancel button closes sheet without firing PATCH', async () => {
    let patchCalled = false;
    server.use(
      http.patch('/api/enrollments/:id', () => {
        patchCalled = true;
        return HttpResponse.json({
          id: 7,
          kid_id: 1,
          offering_id: 1,
          status: 'interested',
          enrolled_at: null,
          notes: null,
          created_at: '2026-05-01T00:00:00Z',
          offering: makeOffering(),
        });
      }),
    );

    const onClose = vi.fn();
    const enrollment = makeEnrollment();

    renderWithQueryClient(
      <EnrollmentEditSheet enrollment={enrollment} kidId={1} onClose={onClose} />,
      new QueryClient(),
    );

    // Verify the sheet is open
    expect(screen.getByText('Edit enrollment')).toBeInTheDocument();

    // Click Cancel button
    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await userEvent.click(cancelButton);

    // Verify onClose was called and PATCH was not called
    expect(onClose).toHaveBeenCalled();
    expect(patchCalled).toBe(false);
  });
});
