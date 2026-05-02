// Mock MUST be first before any imports of modules that use the mocked module
import { vi } from 'vitest';
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
  };
});

import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DigestPreviewPanel } from './DigestPreviewPanel';
import type { KidBrief, DigestPreviewResponse } from '@/lib/types';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const makeKidBrief = (over: Partial<KidBrief> = {}): KidBrief => ({
  id: 1,
  name: 'Sam',
  dob: '2018-01-01',
  interests: ['soccer'],
  active: true,
  ...over,
});

const makeDigestPreview = (over: Partial<DigestPreviewResponse> = {}): DigestPreviewResponse => ({
  subject: 'Daily digest — May 1, 2026',
  body_plain: 'Here is your daily digest.',
  body_html: '<html><body><h1>Daily Digest</h1><p>Your daily updates.</p></body></html>',
  ...over,
});

describe('DigestPreviewPanel', () => {
  it('renders kid picker with all kids; defaults to first kid', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const kids = [makeKidBrief({ id: 1, name: 'Sam' }), makeKidBrief({ id: 2, name: 'Alex' })];
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['digest', 'preview', 1], makeDigestPreview());

    render(<DigestPreviewPanel searchParams={{}} onKidChange={vi.fn()} />, {
      wrapper: makeWrapper(qc),
    });

    const select = screen.getByLabelText(/kid/i) as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe('1');
    expect(screen.getByText('Sam')).toBeInTheDocument();
    expect(screen.getByText('Alex')).toBeInTheDocument();
  });

  it('pre-populates iframe srcDoc when useDigestPreview resolves', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const kids = [makeKidBrief({ id: 1, name: 'Sam' })];
    const preview = makeDigestPreview({
      body_html: '<html><body><h1>Test Digest</h1></body></html>',
    });
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['digest', 'preview', 1], preview);

    render(<DigestPreviewPanel searchParams={{}} onKidChange={vi.fn()} />, {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => {
      const iframe = screen.getByTitle('Digest preview') as HTMLIFrameElement;
      expect(iframe).toBeInTheDocument();
      expect(iframe.getAttribute('srcDoc')).toBe(preview.body_html);
    });
  });

  it('renders subject text above iframe', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const kids = [makeKidBrief({ id: 1, name: 'Sam' })];
    const preview = makeDigestPreview({ subject: 'My Test Subject' });
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['digest', 'preview', 1], preview);

    render(<DigestPreviewPanel searchParams={{}} onKidChange={vi.fn()} />, {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => {
      expect(screen.getByText(/My Test Subject/)).toBeInTheDocument();
    });
  });

  it('switching kid via picker fires onKidChange with new kidId', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const kids = [makeKidBrief({ id: 1, name: 'Sam' }), makeKidBrief({ id: 2, name: 'Alex' })];
    qc.setQueryData(['kids'], kids);
    qc.setQueryData(['digest', 'preview', 1], makeDigestPreview());
    qc.setQueryData(['digest', 'preview', 2], makeDigestPreview());

    const onKidChange = vi.fn();

    render(<DigestPreviewPanel searchParams={{}} onKidChange={onKidChange} />, {
      wrapper: makeWrapper(qc),
    });

    const select = screen.getByLabelText(/kid/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '2' } });

    expect(onKidChange).toHaveBeenCalledWith(2);
  });

  it('shows empty state when no kids: "Add a kid first" with link to /kids/new', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['kids'], []);

    render(<DigestPreviewPanel searchParams={{}} onKidChange={vi.fn()} />, {
      wrapper: makeWrapper(qc),
    });

    expect(screen.getByText(/Add a kid first/i)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Add kid/i });
    expect(link).toHaveAttribute('href', '/kids/new');
  });
});
