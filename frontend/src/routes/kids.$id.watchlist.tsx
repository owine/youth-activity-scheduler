import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { useKid } from '@/lib/queries';
import { KidTabs } from '@/components/layout/KidTabs';

export const Route = createFileRoute('/kids/$id/watchlist')({ component: KidWatchlistPage });

function KidWatchlistPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const { data, isLoading, isError, refetch } = useKid(kidId);

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError || !data) return <ErrorBanner message="Failed to load watchlist" onRetry={() => refetch()} />;

  return (
    <div>
      <KidTabs kidId={kidId} />
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">{data.name} — watchlist</h1>
        <p className="text-sm text-muted-foreground">{data.watchlist.length} entries</p>
      </header>
      {data.watchlist.length === 0 ? (
        <EmptyState>No watchlist entries.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.watchlist.map((w) => (
            <li key={w.id}>
              <Card className="p-3 flex items-start gap-3">
                <div className="flex-1">
                  <div className="font-semibold">{w.pattern}</div>
                  <div className="text-sm text-muted-foreground">
                    {w.site_id ? `Site #${w.site_id}` : 'any site'} · priority {w.priority}
                    {w.notes && ` · ${w.notes}`}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  {w.ignore_hard_gates && <Badge variant="outline">ignores hard gates</Badge>}
                  {!w.active && <Badge variant="secondary">inactive</Badge>}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
