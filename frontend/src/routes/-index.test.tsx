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
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { delay, http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { inboxSummaryFixture } from '@/test/handlers';
import { InboxPage } from './index';

const openAlert = {
  id: 1,
  type: 'new_match' as const,
  kid_id: 1,
  kid_name: 'Sam',
  offering_id: null,
  site_id: null,
  channels: ['email'],
  scheduled_for: '2026-04-20T12:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'k1',
  payload_json: {},
  summary_text: 'Open alert',
  closed_at: null,
  close_reason: null,
};
const closedAlert = {
  ...openAlert,
  id: 2,
  dedup_key: 'k2',
  summary_text: 'Closed alert',
  closed_at: '2026-04-21T12:00:00Z',
  close_reason: 'acknowledged',
};

describe('InboxPage', () => {
  it('keeps "Show closed" checked while the closed alerts load', async () => {
    const urls: string[] = [];
    server.use(
      http.get('/api/inbox/summary', async ({ request }) => {
        urls.push(request.url);
        const withClosed = new URL(request.url).searchParams.get('include_closed') === 'true';
        if (withClosed) await delay(30);
        return HttpResponse.json({
          ...inboxSummaryFixture,
          alerts: withClosed ? [openAlert, closedAlert] : [openAlert],
        });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InboxPage />
      </QueryClientProvider>,
    );

    const toggle = await screen.findByRole('checkbox', { name: /show closed/i });
    await userEvent.click(toggle);

    expect(await screen.findByText('Closed alert')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /show closed/i })).toBeChecked();
    await waitFor(() => expect(urls.some((u) => u.includes('include_closed=true'))).toBe(true));
  });
});
