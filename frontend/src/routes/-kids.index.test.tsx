import { describe, it, expect, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import {
  createRouter,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
} from '@tanstack/react-router';
import { server } from '@/test/server';
import { KidsIndexPage } from './kids.index';

describe('KidsIndexPage', () => {
  afterEach(() => {
    server.resetHandlers();
  });

  it('renders "No kids yet" when the list is empty', async () => {
    // Default handler from test/handlers.ts returns empty array
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const root = createRootRoute({ component: KidsIndexPage });
    const router = createRouter({
      routeTree: root,
      history: createMemoryHistory({ initialEntries: ['/'] }),
    });

    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/No kids yet/i)).toBeInTheDocument();
  });

  it('renders kid cards with name and age', async () => {
    server.use(
      http.get('/api/kids', () =>
        HttpResponse.json([
          {
            id: 1,
            name: 'Sam',
            dob: '2019-05-01',
            interests: [],
            active: true,
          },
          {
            id: 2,
            name: 'Alex',
            dob: '2021-03-15',
            interests: [],
            active: false,
          },
        ]),
      ),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const root = createRootRoute({ component: KidsIndexPage });
    const router = createRouter({
      routeTree: root,
      history: createMemoryHistory({ initialEntries: ['/'] }),
    });

    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Sam')).toBeInTheDocument();
    expect(await screen.findByText('Alex')).toBeInTheDocument();
    // Verify age info is rendered (both kids should have age)
    const ageElements = screen.getAllByText(/years old/i);
    expect(ageElements).toHaveLength(2);
  });

  it('has Add kid button linking to /kids/new', async () => {
    // Default handler returns empty array
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const root = createRootRoute({ component: KidsIndexPage });
    const router = createRouter({
      routeTree: root,
      history: createMemoryHistory({ initialEntries: ['/'] }),
    });

    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    const addKidLink = await screen.findByRole('link', { name: /Add kid/i });
    expect(addKidLink).toHaveAttribute('href', '/kids/new');
  });
});
