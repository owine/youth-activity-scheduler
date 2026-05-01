import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestSendButton } from './TestSendButton';

const makeQc = () => new QueryClient({ defaultOptions: { mutations: { retry: false } } });
const wrap =
  (qc: QueryClient) =>
  ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );

describe('TestSendButton', () => {
  it('is disabled when the dirty prop is true', () => {
    render(<TestSendButton channel="ntfy" label="Send test" dirty />, { wrapper: wrap(makeQc()) });
    expect(screen.getByRole('button', { name: /send test/i })).toBeDisabled();
  });

  it('renders a green Sent pill on success', async () => {
    server.use(
      http.post('/api/notifiers/ntfy/test', () =>
        HttpResponse.json({ ok: true, detail: 'published' }),
      ),
    );
    render(<TestSendButton channel="ntfy" label="Send test" dirty={false} />, {
      wrapper: wrap(makeQc()),
    });
    await userEvent.click(screen.getByRole('button', { name: /send test/i }));
    expect(await screen.findByText(/Sent/i)).toBeInTheDocument();
  });

  it('renders a red Failed pill with detail on failure', async () => {
    server.use(
      http.post('/api/notifiers/ntfy/test', () => HttpResponse.json({ ok: false, detail: 'boom' })),
    );
    render(<TestSendButton channel="ntfy" label="Send test" dirty={false} />, {
      wrapper: wrap(makeQc()),
    });
    await userEvent.click(screen.getByRole('button', { name: /send test/i }));
    expect(await screen.findByText(/Failed.*boom/i)).toBeInTheDocument();
  });
});
