import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { KidForm } from './KidForm';
import type { KidDetail } from '@/lib/types';

// Mock useNavigate to avoid routing in tests
vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router',
  );
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const seedKid = (overrides: Partial<KidDetail> = {}): KidDetail => ({
  id: 1,
  name: 'Sam',
  dob: '2019-05-01',
  interests: ['soccer'],
  active: true,
  availability: {},
  max_distance_mi: null,
  alert_score_threshold: 0.6,
  alert_on: {},
  school_weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
  school_time_start: null,
  school_time_end: null,
  school_year_ranges: [],
  school_holidays: [],
  notes: null,
  watchlist: [],
  ...overrides,
});

describe('KidForm', () => {
  beforeEach(() => {
    // Default MSW handler for useKid query
    server.use(
      http.get('/api/kids/:id', ({ params }) => {
        const id = Number(params.id);
        if (id === 1) {
          return HttpResponse.json(seedKid());
        }
        return HttpResponse.json({ detail: 'Not found' }, { status: 404 });
      }),
      // Default MSW handlers for create/update
      http.post('/api/kids', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: 999,
          name: (body.name as string) || 'New Kid',
          dob: (body.dob as string) || '2020-01-01',
          interests: (body.interests as string[]) || [],
          active: (body.active as boolean) ?? true,
          availability: {},
          max_distance_mi: (body.max_distance_mi as number | null) ?? null,
          alert_score_threshold: (body.alert_score_threshold as number) ?? 0.6,
          alert_on: (body.alert_on as Record<string, boolean>) || {},
          school_weekdays:
            (body.school_weekdays as string[]) || ['mon', 'tue', 'wed', 'thu', 'fri'],
          school_time_start: (body.school_time_start as string | null) ?? null,
          school_time_end: (body.school_time_end as string | null) ?? null,
          school_year_ranges: (body.school_year_ranges as unknown[]) || [],
          school_holidays: (body.school_holidays as string[]) || [],
          notes: (body.notes as string | null) ?? null,
          watchlist: [],
        });
      }),
      http.patch('/api/kids/:id', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          ...seedKid(),
          ...body,
        });
      }),
    );
  });

  it('renders empty form in create mode with Save + Cancel buttons', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<KidForm mode="create" />, { wrapper: makeWrapper(qc) });

    expect(screen.getByLabelText('Name')).toHaveValue('');
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('autofocuses name input in create mode', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<KidForm mode="create" />, { wrapper: makeWrapper(qc) });
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('pre-populates form fields in edit mode', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<KidForm mode="edit" id={1} />, { wrapper: makeWrapper(qc) });

    await waitFor(() => {
      expect(screen.getByLabelText('Name')).toHaveValue('Sam');
    });
    expect(screen.getByLabelText('Date of Birth')).toHaveValue('2019-05-01');
  });

  it('shows confirm dialog on dirty cancel', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<KidForm mode="create" />, { wrapper: makeWrapper(qc) });

    const nameInput = screen.getByLabelText('Name');
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });

    // Make form dirty
    await userEvent.type(nameInput, 'Alex');

    // Click cancel
    await userEvent.click(cancelBtn);

    // Dialog should appear
    await waitFor(() => {
      expect(screen.getByText(/discard changes/i)).toBeInTheDocument();
    });
  });

  it('does not show confirm dialog on clean cancel', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<KidForm mode="create" />, { wrapper: makeWrapper(qc) });

    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    await userEvent.click(cancelBtn);

    // No dialog should appear
    expect(screen.queryByText(/discard changes/i)).not.toBeInTheDocument();
  });

  it('renders active field in edit mode', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<KidForm mode="edit" id={1} />, { wrapper: makeWrapper(qc) });

    // Wait for the form to load by checking for the Name field
    await waitFor(() => {
      expect(screen.getByLabelText('Name')).toBeInTheDocument();
    });

    // Active field should be present
    expect(screen.getByLabelText('Active')).toBeInTheDocument();
  });
});
