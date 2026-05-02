import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { OutboxFilterBar } from './OutboxFilterBar';
import { OutboxRow } from './OutboxRow';
import { useAlerts, useKids } from '@/lib/queries';
import type { OutboxFilterState, AlertStatus } from '@/lib/types';

interface Props {
  searchParams: Record<string, string | undefined>;
  onFiltersChange: (next: OutboxFilterState) => void;
  onClearFilters: () => void;
}

function parseSearchToFilters(s: Record<string, string | undefined>): OutboxFilterState {
  return {
    kidId: s.kid ? Number(s.kid) : null,
    type: s.type ?? null,
    status: (s.status as AlertStatus | undefined) ?? null,
    since: s.since ?? null,
    until: s.until ?? null,
    page: s.page ? Number(s.page) : 0,
  };
}

export function OutboxPanel({ searchParams, onFiltersChange, onClearFilters }: Props) {
  const filters = parseSearchToFilters(searchParams);
  const kids = useKids();
  const { data, isLoading, isError, refetch } = useAlerts(filters);

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError || !data) {
    return <ErrorBanner message="Failed to load alerts" onRetry={() => refetch()} />;
  }

  const { items, total, offset } = data;
  const start = offset + 1;
  const end = offset + items.length;
  const hasNext = end < total;
  const hasPrev = offset > 0;

  return (
    <div className="space-y-4">
      <OutboxFilterBar value={filters} onChange={onFiltersChange} kids={kids.data ?? []} />
      {items.length === 0 ? (
        <EmptyState>
          No alerts match your filters.{' '}
          <button type="button" className="underline" onClick={() => onClearFilters()}>
            Clear filters
          </button>
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {items.map((a) => (
            <li key={a.id}>
              <OutboxRow alert={a} />
            </li>
          ))}
        </ul>
      )}
      {total > 0 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Showing {start}–{end} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!hasPrev}
              onClick={() => onFiltersChange({ ...filters, page: filters.page - 1 })}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasNext}
              onClick={() => onFiltersChange({ ...filters, page: filters.page + 1 })}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
