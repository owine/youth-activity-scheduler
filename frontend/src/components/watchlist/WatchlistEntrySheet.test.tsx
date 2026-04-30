import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { WatchlistEntrySheet } from './WatchlistEntrySheet';
import type { WatchlistEntry } from '@/lib/types';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const seedEntry = (overrides: Partial<WatchlistEntry> = {}): WatchlistEntry => ({
  id: 1,
  kid_id: 99,
  pattern: 'soccer camp',
  priority: 'normal',
  site_id: null,
  notes: 'summer only',
  active: true,
  ignore_hard_gates: false,
  created_at: '2026-04-30T00:00:00Z',
  ...overrides,
});

describe('WatchlistEntrySheet', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    mockOnClose.mockClear();
    // Default MSW handlers for create/update/delete
    server.use(
      http.post('/api/kids/:kidId/watchlist', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: 42,
            kid_id: 99,
            pattern: (body.pattern as string) || 'test',
            priority: (body.priority as string) || 'normal',
            site_id: (body.site_id as number | null) ?? null,
            notes: (body.notes as string | null) ?? null,
            active: (body.active as boolean) ?? true,
            ignore_hard_gates: (body.ignore_hard_gates as boolean) ?? false,
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
      http.patch('/api/watchlist/:entryId', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            ...seedEntry(),
            ...body,
          },
          { status: 200 },
        );
      }),
      http.delete('/api/watchlist/:entryId', () => {
        return HttpResponse.json({}, { status: 204 });
      }),
    );
  });

  it('renders empty pattern field in add mode', () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<WatchlistEntrySheet kidId={99} mode="create" open={true} onClose={mockOnClose} />, {
      wrapper: makeWrapper(qc),
    });

    const patternInput = screen.getByLabelText(/pattern/i) as HTMLInputElement;
    expect(patternInput).toBeInTheDocument();
    expect(patternInput.value).toBe('');
  });

  it('renders Save and Cancel buttons in add mode', () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<WatchlistEntrySheet kidId={99} mode="create" open={true} onClose={mockOnClose} />, {
      wrapper: makeWrapper(qc),
    });

    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('pre-populates form fields in edit mode', () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const entry = seedEntry({ pattern: 'tennis match', priority: 'high' });
    render(
      <WatchlistEntrySheet
        kidId={99}
        mode="edit"
        entry={entry}
        open={true}
        onClose={mockOnClose}
      />,
      { wrapper: makeWrapper(qc) },
    );

    expect(screen.getByLabelText(/pattern/i)).toHaveValue('tennis match');
    const prioritySelect = screen.getByLabelText(/priority/i) as HTMLSelectElement;
    expect(prioritySelect.value).toBe('high');
  });

  it('submits valid form in add mode and calls onClose', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post('/api/kids/:kidId/watchlist', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        capturedBody = body;
        return HttpResponse.json(
          {
            id: 42,
            kid_id: 99,
            pattern: body.pattern || 'test',
            priority: body.priority || 'normal',
            site_id: (body.site_id as number | null) ?? null,
            notes: (body.notes as string | null) ?? null,
            active: (body.active as boolean) ?? true,
            ignore_hard_gates: (body.ignore_hard_gates as boolean) ?? false,
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );

    render(<WatchlistEntrySheet kidId={99} mode="create" open={true} onClose={mockOnClose} />, {
      wrapper: makeWrapper(qc),
    });

    const patternInput = screen.getByLabelText(/pattern/i) as HTMLInputElement;
    const saveBtn = screen.getByRole('button', { name: /save/i });

    await userEvent.type(patternInput, 'basketball');
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(capturedBody).toEqual(
        expect.objectContaining({
          pattern: 'basketball',
        }),
      );
    });

    await waitFor(() => {
      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  it('shows ErrorBanner on server error and keeps sheet open', async () => {
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });

    server.use(
      http.post('/api/kids/:kidId/watchlist', () =>
        HttpResponse.json({ detail: 'Duplicate pattern' }, { status: 400 }),
      ),
    );

    render(<WatchlistEntrySheet kidId={99} mode="create" open={true} onClose={mockOnClose} />, {
      wrapper: makeWrapper(qc),
    });

    const patternInput = screen.getByLabelText(/pattern/i) as HTMLInputElement;
    const saveBtn = screen.getByRole('button', { name: /save/i });

    await userEvent.type(patternInput, 'basketball');
    await userEvent.click(saveBtn);

    // Error should appear
    await screen.findByText(/duplicate pattern/i);
    expect(screen.getByText(/duplicate pattern/i)).toBeInTheDocument();

    // Sheet should still be open (mockOnClose not called)
    expect(mockOnClose).not.toHaveBeenCalled();
  });
});
