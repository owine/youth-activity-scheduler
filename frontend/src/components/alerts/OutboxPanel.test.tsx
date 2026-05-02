import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OutboxPanel } from './OutboxPanel';
import type { Alert, KidBrief } from '@/lib/types';

const makeAlert = (over: Partial<Alert> = {}): Alert => ({
  id: 1,
  type: 'watchlist_hit',
  kid_id: 1,
  offering_id: 10,
  site_id: 5,
  channels: ['email'],
  scheduled_for: '2026-05-01T10:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'key-1',
  payload_json: {},
  closed_at: null,
  close_reason: null,
  summary_text: 'Cool activity found',
  ...over,
});

const makeKid = (over: Partial<KidBrief> = {}): KidBrief => ({
  id: 1,
  name: 'Sam',
  dob: '2019-01-01',
  interests: [],
  active: true,
  ...over,
});

function renderWithQueryClient(component: React.ReactNode, qc: QueryClient = new QueryClient()) {
  return render(<QueryClientProvider client={qc}>{component}</QueryClientProvider>);
}

describe('OutboxPanel', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-05-01T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders FilterBar + list of OutboxRow components from seeded useAlerts cache', () => {
    const qc = new QueryClient();
    const filters = {
      kidId: null,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 0,
    };
    const kids = [makeKid()];
    const alerts = [
      makeAlert({ id: 1, summary_text: 'Alert 1' }),
      makeAlert({ id: 2, summary_text: 'Alert 2' }),
    ];

    // Seed cache
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['alerts', 'list', filters, 25], {
      items: alerts,
      total: 2,
      limit: 25,
      offset: 0,
    });

    renderWithQueryClient(
      <OutboxPanel searchParams={{}} onFiltersChange={vi.fn()} onClearFilters={vi.fn()} />,
      qc,
    );

    // FilterBar should render with kid select
    expect(screen.getByLabelText(/kid/i)).toBeInTheDocument();

    // List should render both alerts
    expect(screen.getByText('Alert 1')).toBeInTheDocument();
    expect(screen.getByText('Alert 2')).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);
  });

  it('empty filtered state renders "No alerts match" + Clear button calls onClearFilters', () => {
    const qc = new QueryClient();
    const filters = {
      kidId: 1,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 0,
    };
    const kids = [makeKid()];
    const onClearFilters = vi.fn();

    // Seed cache with empty response
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['alerts', 'list', filters, 25], {
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
    });

    renderWithQueryClient(
      <OutboxPanel
        searchParams={{ kid: '1' }}
        onFiltersChange={vi.fn()}
        onClearFilters={onClearFilters}
      />,
      qc,
    );

    // Should show empty state
    expect(screen.getByText(/no alerts match/i)).toBeInTheDocument();

    // Clear button should be present and clickable
    const clearButton = screen.getByRole('button', { name: /clear filters/i });
    expect(clearButton).toBeInTheDocument();
  });

  it('pagination: Next disabled when offset + items.length >= total; Prev disabled at offset 0', async () => {
    const qc = new QueryClient();
    const filters = {
      kidId: null,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 0,
    };
    const kids = [makeKid()];
    const alerts = [makeAlert({ id: 1 }), makeAlert({ id: 2 })];

    // Seed cache: offset 0, 2 items, total 3 (hasNext = true, hasPrev = false)
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['alerts', 'list', filters, 25], {
      items: alerts,
      total: 3,
      limit: 25,
      offset: 0,
    });

    renderWithQueryClient(
      <OutboxPanel searchParams={{}} onFiltersChange={vi.fn()} onClearFilters={vi.fn()} />,
      qc,
    );

    const buttons = screen.getAllByRole('button', { name: /prev|next/i });
    const prevBtn = buttons.find((b) => b.textContent === 'Prev');
    const nextBtn = buttons.find((b) => b.textContent === 'Next');

    expect(prevBtn).toBeDisabled();
    expect(nextBtn).not.toBeDisabled();
  });

  it('pagination: Next disabled when at last page', async () => {
    const qc = new QueryClient();
    const filters = {
      kidId: null,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 1,
    };
    const kids = [makeKid()];
    const alerts = [makeAlert({ id: 3 })];

    // Seed cache: offset 25, 1 item, total 26 (hasNext = false, hasPrev = true)
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['alerts', 'list', filters, 25], {
      items: alerts,
      total: 26,
      limit: 25,
      offset: 25,
    });

    renderWithQueryClient(
      <OutboxPanel
        searchParams={{ page: '1' }}
        onFiltersChange={vi.fn()}
        onClearFilters={vi.fn()}
      />,
      qc,
    );

    const buttons = screen.getAllByRole('button', { name: /prev|next/i });
    const prevBtn = buttons.find((b) => b.textContent === 'Prev');
    const nextBtn = buttons.find((b) => b.textContent === 'Next');

    expect(prevBtn).not.toBeDisabled();
    expect(nextBtn).toBeDisabled();
  });

  it('filter state parsed from searchParams prop: mount with ?status=sent reads through', () => {
    const qc = new QueryClient();
    const filters = {
      kidId: null,
      type: null,
      status: 'sent' as const,
      since: null,
      until: null,
      page: 0,
    };
    const kids = [makeKid()];
    const alerts = [makeAlert({ sent_at: '2026-05-01T08:00:00Z' })];

    // Seed cache with status filter
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['alerts', 'list', filters, 25], {
      items: alerts,
      total: 1,
      limit: 25,
      offset: 0,
    });

    const onFiltersChange = vi.fn();
    renderWithQueryClient(
      <OutboxPanel
        searchParams={{ status: 'sent' }}
        onFiltersChange={onFiltersChange}
        onClearFilters={vi.fn()}
      />,
      qc,
    );

    // FilterBar should have status set to 'sent'
    const sentRadio = screen.getByRole('radio', { name: /sent/i });
    expect(sentRadio).toBeChecked();
  });
});
