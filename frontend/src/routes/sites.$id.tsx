import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useSite, useSiteCrawls } from '@/lib/queries';
import { CrawlHistoryList } from '@/components/sites/CrawlHistoryList';
import { fmt } from '@/lib/format';
import { MuteButton } from '@/components/common/MuteButton';
import { Button } from '@/components/ui/button';
import { useUpdateSiteMute, useCrawlNow, useToggleSiteActive } from '@/lib/mutations';

export const Route = createFileRoute('/sites/$id')({ component: SiteDetailPage });

function SiteDetailPage() {
  const { id } = Route.useParams();
  const siteId = Number(id);
  const site = useSite(siteId);
  const crawls = useSiteCrawls(siteId);
  const muteSite = useUpdateSiteMute();
  const crawlNow = useCrawlNow();
  const toggleActive = useToggleSiteActive();
  const [crawlQueued, setCrawlQueued] = useState(false);

  if (site.isLoading) return <Skeleton className="h-32 w-full" />;
  if (site.isError || !site.data)
    return <ErrorBanner message="Failed to load site" onRetry={() => site.refetch()} />;

  const s = site.data;

  const handleCrawlNow = () => {
    crawlNow.mutate(
      { siteId },
      {
        onSuccess: () => {
          setCrawlQueued(true);
          setTimeout(() => setCrawlQueued(false), 2000);
        },
      },
    );
  };

  const isActive = s.active ?? true;

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{s.name}</h1>
          <p className="text-sm text-muted-foreground">
            {s.base_url} · adapter: {s.adapter}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={handleCrawlNow} disabled={crawlNow.isPending}>
            {crawlQueued ? 'Queued ✓' : 'Crawl now'}
          </Button>
          <Button
            variant="outline"
            onClick={() => toggleActive.mutate({ siteId, active: !isActive })}
            disabled={toggleActive.isPending}
          >
            {isActive ? 'Pause' : 'Resume'}
          </Button>
          {!isActive && <span className="text-xs font-semibold text-muted-foreground">Paused</span>}
          <MuteButton
            mutedUntil={s.muted_until ?? null}
            onChange={(mutedUntil) => muteSite.mutate({ siteId, mutedUntil })}
            isPending={muteSite.isPending}
          />
        </div>
      </header>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">
          Pages ({s.pages.length})
        </h2>
        <ul className="space-y-1.5 text-sm">
          {s.pages.map((p) => (
            <li key={p.id} className="rounded-md border border-border p-2">
              <div className="font-mono text-xs break-all">{p.url}</div>
              <div className="text-muted-foreground text-xs mt-0.5">
                {p.kind}
                {p.last_fetched && ` · last fetched ${fmt(p.last_fetched)}`}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">
          Recent crawl history
        </h2>
        <CrawlHistoryList crawls={crawls.data} isLoading={crawls.isLoading} />
      </section>
    </div>
  );
}
