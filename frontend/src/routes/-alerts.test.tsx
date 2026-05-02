import { vi } from 'vitest';

interface MockOutboxPanelProps {
  searchParams: Record<string, string>;
  onFiltersChange: (filters: {
    page: number;
    kidId: null;
    type: null;
    status: null;
    since: null;
    until: null;
  }) => void;
  onClearFilters: () => void;
}

interface MockDigestPanelProps {
  searchParams: Record<string, string>;
  onKidChange: (kidId: number) => void;
}

// Mock the panels first
vi.mock('@/components/alerts/OutboxPanel', () => ({
  OutboxPanel: ({ searchParams, onFiltersChange, onClearFilters }: MockOutboxPanelProps) => (
    <div data-testid="outbox-panel">
      Outbox Panel (searchParams: {JSON.stringify(searchParams)})
      <button
        onClick={() =>
          onFiltersChange({
            page: 1,
            kidId: null,
            type: null,
            status: null,
            since: null,
            until: null,
          })
        }
      >
        Filter
      </button>
      <button onClick={() => onClearFilters()}>Clear</button>
    </div>
  ),
}));

vi.mock('@/components/alerts/DigestPreviewPanel', () => ({
  DigestPreviewPanel: ({ searchParams, onKidChange }: MockDigestPanelProps) => (
    <div data-testid="digest-panel">
      Digest Preview Panel (searchParams: {JSON.stringify(searchParams)})
      <button onClick={() => onKidChange(1)}>Change Kid</button>
    </div>
  ),
}));

// Mock router after panels
vi.mock('@tanstack/react-router', async () => {
  const actual =
    await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router');
  return {
    ...actual,
    Link: ({
      to,
      search,
      children,
      ...props
    }: {
      to: string;
      search?: Record<string, unknown>;
      children?: React.ReactNode;
    } & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) => {
      // Build href from route and search params
      let href = to;
      if (search && typeof search === 'object') {
        const params = new URLSearchParams();
        Object.entries(search).forEach(([key, value]) => {
          if (value !== null && value !== undefined) {
            params.set(key, String(value));
          }
        });
        const queryString = params.toString();
        if (queryString) {
          href = `${href}?${queryString}`;
        }
      }
      return (
        <a href={href} {...props}>
          {children}
        </a>
      );
    },
    useNavigate: () => vi.fn(),
  };
});

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AlertsPage } from './alerts';

describe('AlertsPage', () => {
  it('renders OutboxPanel by default when no ?tab= param', () => {
    const search: Record<string, string> = {};

    render(<AlertsPage searchParams={search} />);

    expect(screen.getByTestId('outbox-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('digest-panel')).not.toBeInTheDocument();
    // Verify the outbox panel is rendered by checking for its content
    expect(screen.getByText(/Outbox Panel/)).toBeInTheDocument();
  });

  it('renders DigestPreviewPanel when ?tab=digest', () => {
    const search: Record<string, string> = { tab: 'digest' };

    render(<AlertsPage searchParams={search} />);

    expect(screen.getByTestId('digest-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('outbox-panel')).not.toBeInTheDocument();
    // Verify the digest panel is rendered by checking for its content
    expect(screen.getByText(/Digest Preview Panel/)).toBeInTheDocument();
  });
});
