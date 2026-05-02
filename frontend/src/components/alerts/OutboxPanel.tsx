import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { OutboxFilterBar } from './OutboxFilterBar';
import { OutboxRow } from './OutboxRow';
import { useAlerts, useKids } from '@/lib/queries';
import { useBulkCloseAlerts } from '@/lib/mutations';
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
  const bulkClose = useBulkCloseAlerts();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError || !data) {
    return <ErrorBanner message="Failed to load alerts" onRetry={() => refetch()} />;
  }

  const { items, total, offset } = data;
  const start = offset + 1;
  const end = offset + items.length;
  const hasNext = end < total;
  const hasPrev = offset > 0;

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectableIds = items.filter((a) => a.closed_at == null).map((a) => a.id);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectableIds));
    }
  };

  const handleBulkClose = async (reason: 'acknowledged' | 'dismissed') => {
    if (selected.size === 0) return;
    await bulkClose.mutateAsync({ alertIds: [...selected], reason });
    setSelected(new Set());
  };

  return (
    <div className="space-y-4">
      <OutboxFilterBar value={filters} onChange={onFiltersChange} kids={kids.data ?? []} />
      {selected.size > 0 && (
        <div className="flex items-center gap-2 rounded border border-border bg-accent/30 px-3 py-2 text-sm">
          <span className="font-medium">{selected.size} selected</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={bulkClose.isPending}
            onClick={() => handleBulkClose('acknowledged')}
          >
            Close as acknowledged
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={bulkClose.isPending}
            onClick={() => handleBulkClose('dismissed')}
          >
            Close as dismissed
          </Button>
          <button
            type="button"
            className="ml-auto text-xs text-muted-foreground hover:text-foreground underline"
            onClick={() => setSelected(new Set())}
          >
            Clear selection
          </button>
        </div>
      )}
      {items.length === 0 ? (
        <EmptyState>
          No alerts match your filters.{' '}
          <button type="button" className="underline" onClick={() => onClearFilters()}>
            Clear filters
          </button>
        </EmptyState>
      ) : (
        <>
          {selectableIds.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleSelectAll}
                aria-label="Select all open alerts on this page"
              />
              Select all on this page
            </label>
          )}
          <ul className="space-y-2">
            {items.map((a) => (
              <li key={a.id}>
                <OutboxRow alert={a} selected={selected.has(a.id)} onToggleSelect={toggleSelect} />
              </li>
            ))}
          </ul>
        </>
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
