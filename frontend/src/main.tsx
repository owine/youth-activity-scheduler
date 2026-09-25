import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import './styles/globals.css';
import { routeTree } from './routeTree.gen';
import { AppErrorBoundary } from '@/components/common/AppErrorBoundary';
import { initSentry, reportRouteError } from '@/lib/sentry';

// Before anything renders, so errors during the first render are captured.
// A no-op unless the backend rendered a browser DSN into index.html.
initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: 2,
    },
  },
});

const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultOnCatch: reportRouteError,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AppErrorBoundary>
  </StrictMode>,
);
