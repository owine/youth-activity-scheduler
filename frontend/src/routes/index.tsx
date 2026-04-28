import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { AlertsSection } from '@/components/inbox/AlertsSection';
import { NewMatchesByKidSection } from '@/components/inbox/NewMatchesByKidSection';
import { SiteActivitySection } from '@/components/inbox/SiteActivitySection';
import { useInboxSummary } from '@/lib/queries';

export const Route = createFileRoute('/')({ component: InboxPage });

function InboxPage() {
  const { data, isLoading, isError, error, refetch } = useInboxSummary();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <ErrorBanner
        message={(error as Error)?.message ?? 'Unknown error'}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">What's new this week</h1>
        <p className="text-sm text-muted-foreground">
          Since {new Date(data.window_start).toLocaleDateString()} ·{' '}
          {data.new_matches_by_kid.length} kid{data.new_matches_by_kid.length === 1 ? '' : 's'}
        </p>
      </header>
      <AlertsSection alerts={data.alerts} />
      <NewMatchesByKidSection rows={data.new_matches_by_kid} />
      <SiteActivitySection activity={data.site_activity} />
    </div>
  );
}
