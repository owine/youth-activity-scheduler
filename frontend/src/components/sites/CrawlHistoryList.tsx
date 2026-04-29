import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import type { CrawlRun } from '@/lib/types';
import { fmt } from '@/lib/format';

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline-solid'> = {
  ok: 'secondary',
  failed: 'destructive',
  skipped: 'outline-solid',
};

export function CrawlHistoryList({ crawls, isLoading }: { crawls: CrawlRun[] | undefined; isLoading: boolean }) {
  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (!crawls || crawls.length === 0) return <p className="text-sm text-muted-foreground">No crawl history.</p>;
  return (
    <ul className="space-y-1.5">
      {crawls.map((c) => (
        <li key={c.id} className="rounded-md border border-border p-2.5 text-sm">
          <div className="flex items-center gap-3">
            <Badge variant={statusVariant[c.status] ?? 'outline-solid'}>{c.status}</Badge>
            <span className="text-muted-foreground">{fmt(c.started_at)}</span>
            <span className="ml-auto">{c.pages_fetched} pages · {c.changes_detected} changes</span>
          </div>
          {c.error_text && <p className="mt-1 text-xs text-destructive">{c.error_text}</p>}
        </li>
      ))}
    </ul>
  );
}
