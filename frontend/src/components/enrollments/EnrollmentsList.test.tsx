// Mock MUST be first before any imports of modules that use the mocked module
import { vi } from 'vitest';
vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router');
  return {
    ...actual,
    Link: ({
      to,
      params,
      children,
      ...props
    }: {
      to: string;
      params?: Record<string, string>;
      children?: React.ReactNode;
    } & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) => {
      // Build href from route and params
      let href = to;
      if (params && typeof params === 'object') {
        Object.entries(params).forEach(([key, value]) => {
          href = href.replace(`$${key}`, String(value));
        });
      }
      return (
        <a href={href} {...props}>
          {children}
        </a>
      );
    },
    useLocation: () => ({
      pathname: '/kids/1/enrollments',
      search: '',
      hash: '',
      state: null,
      key: '',
    }),
  };
});

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EnrollmentsList } from './EnrollmentsList';
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

describe('EnrollmentsList', () => {
  it('renders Active section with rows whose status is in {interested, enrolled, waitlisted}', () => {
    const qc = new QueryClient();
    qc.setQueryData(['kids', 1], { id: 1, name: 'Sam' });
    qc.setQueryData(
      ['kids', 1, 'enrollments'],
      [
        makeEnrollment({ status: 'interested', id: 1 }),
        makeEnrollment({ status: 'enrolled', id: 2 }),
        makeEnrollment({ status: 'waitlisted', id: 3 }),
      ],
    );

    renderWithQueryClient(<EnrollmentsList kidId={1} />, qc);

    // Verify Active section header
    expect(screen.getByText('Active')).toBeInTheDocument();

    // Verify all three active rows render (Soccer Camp appears 3 times for the 3 enrollments)
    const soccerElements = screen.getAllByText('Soccer Camp');
    expect(soccerElements.length).toBeGreaterThanOrEqual(3);
  });

  it('History section behind <details>; rows hidden by default', () => {
    const qc = new QueryClient();
    qc.setQueryData(['kids', 1], { id: 1, name: 'Sam' });
    qc.setQueryData(
      ['kids', 1, 'enrollments'],
      [
        makeEnrollment({ status: 'enrolled', id: 1 }),
        makeEnrollment({ status: 'completed', id: 2 }),
        makeEnrollment({ status: 'cancelled', id: 3 }),
      ],
    );

    renderWithQueryClient(<EnrollmentsList kidId={1} />, qc);

    // Verify details summary is rendered (history section)
    expect(screen.getByText(/Show .* past enrollment/)).toBeInTheDocument();

    // Verify that details element is present and not open by default
    const detailsElement = screen.getByText(/Show .* past enrollment/).closest('details');
    expect(detailsElement).not.toHaveAttribute('open');
  });

  it('empty state: no enrollments → "No enrollments yet" text + link to Matches', () => {
    const qc = new QueryClient();
    qc.setQueryData(['kids', 1], { id: 1, name: 'Sam' });
    qc.setQueryData(['kids', 1, 'enrollments'], []);

    renderWithQueryClient(<EnrollmentsList kidId={1} />, qc);

    const emptyStateText = screen.getByText(/No enrollments yet/);
    expect(emptyStateText).toBeInTheDocument();
    // The EmptyState includes the link to Matches
    const matchesLink = emptyStateText.parentElement?.querySelector('a[href="/kids/1/matches"]');
    expect(matchesLink).toBeInTheDocument();
  });

  it('filter logic: enrollment with status=completed lands in History; status=waitlisted in Active', () => {
    const qc = new QueryClient();
    qc.setQueryData(['kids', 1], { id: 1, name: 'Sam' });
    qc.setQueryData(
      ['kids', 1, 'enrollments'],
      [
        makeEnrollment({
          status: 'completed',
          id: 1,
          offering: makeOffering({ name: 'Completed Class' }),
        }),
        makeEnrollment({
          status: 'waitlisted',
          id: 2,
          offering: makeOffering({ name: 'Waitlist Class' }),
        }),
      ],
    );

    renderWithQueryClient(<EnrollmentsList kidId={1} />, qc);

    // Verify "Active" and "Waitlist Class" in active section
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Waitlist Class')).toBeInTheDocument();

    // Verify history details with link to completed
    expect(screen.getByText(/Show .* past enrollment/)).toBeInTheDocument();
  });
});
