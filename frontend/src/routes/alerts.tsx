import { createFileRoute, Link, useNavigate } from '@tanstack/react-router';
import { OutboxPanel } from '@/components/alerts/OutboxPanel';
import { DigestPreviewPanel } from '@/components/alerts/DigestPreviewPanel';
import { cn } from '@/lib/utils';
import type { OutboxFilterState } from '@/lib/types';

export const Route = createFileRoute('/alerts')({
  component: AlertsPageRoute,
  validateSearch: (s: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(s).filter(([, v]) => typeof v === 'string')) as Record<
      string,
      string
    >,
});

function filtersToSearch(f: OutboxFilterState): Record<string, string> {
  const out: Record<string, string> = { tab: 'outbox' };
  if (f.kidId != null) out.kid = String(f.kidId);
  if (f.type) out.type = f.type;
  if (f.status) out.status = f.status;
  if (f.since) out.since = f.since;
  if (f.until) out.until = f.until;
  if (f.page > 0) out.page = String(f.page);
  return out;
}

export function AlertsPage({ searchParams }: { searchParams: Record<string, string> }) {
  const tab = searchParams.tab === 'digest' ? 'digest' : 'outbox';
  const navigate = useNavigate();

  const handleFiltersChange = (next: OutboxFilterState) => {
    navigate({ to: '/alerts', search: filtersToSearch(next) });
  };

  const handleClearFilters = () => {
    navigate({ to: '/alerts', search: { tab: 'outbox' } });
  };

  const handleKidChange = (kidId: number) => {
    navigate({
      to: '/alerts',
      search: { ...searchParams, tab: 'digest', kid_digest: String(kidId) },
    });
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Alerts</h1>
      <nav className="border-b border-border flex gap-2 mb-4">
        <Link
          to="/alerts"
          search={{ tab: 'outbox' }}
          className={cn(
            'px-3 py-2 text-sm border-b-2 -mb-px',
            tab === 'outbox'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          Outbox
        </Link>
        <Link
          to="/alerts"
          search={{ tab: 'digest' }}
          className={cn(
            'px-3 py-2 text-sm border-b-2 -mb-px',
            tab === 'digest'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          Digest preview
        </Link>
      </nav>
      {tab === 'outbox' ? (
        <OutboxPanel
          searchParams={searchParams}
          onFiltersChange={handleFiltersChange}
          onClearFilters={handleClearFilters}
        />
      ) : (
        <DigestPreviewPanel searchParams={searchParams} onKidChange={handleKidChange} />
      )}
    </div>
  );
}

function AlertsPageRoute() {
  const search = Route.useSearch();
  return <AlertsPage searchParams={search} />;
}
