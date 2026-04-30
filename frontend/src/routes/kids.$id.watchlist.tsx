import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { X } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { useKid } from '@/lib/queries';
import { useDeleteWatchlistEntry } from '@/lib/mutations';
import { KidTabs } from '@/components/layout/KidTabs';
import { WatchlistEntrySheet } from '@/components/watchlist/WatchlistEntrySheet';
import type { WatchlistEntry } from '@/lib/types';

export function KidWatchlistPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const { data, isLoading, isError, refetch } = useKid(kidId);
  const deleteEntry = useDeleteWatchlistEntry();
  const [editing, setEditing] = useState<WatchlistEntry | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; entryId?: number }>({
    open: false,
  });

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError || !data)
    return <ErrorBanner message="Failed to load watchlist" onRetry={() => refetch()} />;

  const handleDeleteConfirm = async () => {
    if (deleteConfirm.entryId) {
      try {
        await deleteEntry.mutateAsync({ kidId, entryId: deleteConfirm.entryId });
        setDeleteConfirm({ open: false });
      } catch (err) {
        // Error handling is done by the mutation
        console.error('Failed to delete watchlist entry:', err);
      }
    }
  };

  return (
    <div>
      <KidTabs kidId={kidId} />
      <header className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{data.name} — watchlist</h1>
          <p className="text-sm text-muted-foreground">{data.watchlist.length} entries</p>
        </div>
        <Button onClick={() => setCreating(true)}>Add watchlist entry</Button>
      </header>
      {data.watchlist.length === 0 ? (
        <EmptyState>No watchlist entries.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.watchlist.map((w) => (
            <li key={w.id} onClick={() => setEditing(w)} className="cursor-pointer">
              <Card className="p-3 flex items-start gap-3 hover:bg-accent/50 transition-colors">
                <div className="flex-1">
                  <div className="font-semibold">{w.pattern}</div>
                  <div className="text-sm text-muted-foreground">
                    {w.site_id ? `Site #${w.site_id}` : 'any site'} · priority {w.priority}
                    {w.notes && ` · ${w.notes}`}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <div className="flex gap-1">
                    {w.ignore_hard_gates && <Badge variant="outline">ignores hard gates</Badge>}
                    {!w.active && <Badge variant="secondary">inactive</Badge>}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteConfirm({ open: true, entryId: w.id });
                    }}
                    className="text-muted-foreground hover:text-destructive transition-colors"
                    aria-label="Delete entry"
                    type="button"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <WatchlistEntrySheet
        kidId={kidId}
        mode="create"
        open={creating}
        onClose={() => setCreating(false)}
      />

      {editing && (
        <WatchlistEntrySheet
          kidId={kidId}
          mode="edit"
          entry={editing}
          open={editing !== null}
          onClose={() => setEditing(null)}
        />
      )}

      <ConfirmDialog
        open={deleteConfirm.open}
        onOpenChange={(open) => setDeleteConfirm({ ...deleteConfirm, open })}
        title="Delete watchlist entry?"
        description={`Are you sure you want to delete this entry? This action cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={handleDeleteConfirm}
      />
    </div>
  );
}

export const Route = createFileRoute('/kids/$id/watchlist')({ component: KidWatchlistPage });
