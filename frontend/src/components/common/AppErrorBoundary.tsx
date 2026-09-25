import * as Sentry from '@sentry/react';
import { AlertCircle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

function CrashFallback() {
  return (
    <div className="mx-auto max-w-lg p-6">
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Something went wrong</AlertTitle>
        <AlertDescription className="flex items-center justify-between gap-3">
          <span>The page hit an unexpected error.</span>
          <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  );
}

/**
 * Last-resort boundary around the whole app. Errors inside a route are caught
 * by the router first (see reportRouteError); this one catches the rest —
 * providers, the router itself — and reports them when Sentry is initialised.
 */
export function AppErrorBoundary({ children }: { children: React.ReactNode }) {
  return <Sentry.ErrorBoundary fallback={<CrashFallback />}>{children}</Sentry.ErrorBoundary>;
}
