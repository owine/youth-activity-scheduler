import { createFileRoute, Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useSites } from '@/lib/queries';
import { relDate } from '@/lib/format';

export const Route = createFileRoute('/sites/')({ component: SitesPage });

function SitesPage() {
  const { data, isLoading, isError, refetch } = useSites();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data)
    return <ErrorBanner message="Failed to load sites" onRetry={() => refetch()} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Sites</h1>
        <Button asChild>
          <Link to="/sites/new">Add site</Link>
        </Button>
      </div>
      {data.length === 0 ? (
        <EmptyState>No sites tracked yet.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.map((s) => {
            const lastFetched =
              s.pages
                .map((p) => p.last_fetched)
                .filter(Boolean)
                .sort()
                .reverse()[0] ?? null;
            return (
              <li key={s.id}>
                <Link to="/sites/$id" params={{ id: String(s.id) }}>
                  <Card className="p-3 hover:bg-accent transition">
                    <div className="flex items-center gap-3">
                      <div className="flex-1">
                        <div className="font-semibold">{s.name}</div>
                        <div className="text-sm text-muted-foreground">
                          {s.adapter} · {s.pages.length} page{s.pages.length === 1 ? '' : 's'}
                          {lastFetched && ` · last crawled ${relDate(lastFetched)}`}
                        </div>
                      </div>
                      {s.muted_until && <Badge variant="secondary">muted</Badge>}
                      {!s.active && <Badge variant="outline">inactive</Badge>}
                    </div>
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
