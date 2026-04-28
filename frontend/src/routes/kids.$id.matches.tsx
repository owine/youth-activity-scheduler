import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { useKid, useKidMatches } from '@/lib/queries';
import { groupByUrgency } from '@/lib/matches';
import { UrgencyGroup } from '@/components/matches/UrgencyGroup';
import { MatchDetailDrawer } from '@/components/matches/MatchDetailDrawer';
import type { Match } from '@/lib/types';

export const Route = createFileRoute('/kids/$id/matches')({ component: KidMatchesPage });

function KidMatchesPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const kid = useKid(kidId);
  const matches = useKidMatches(kidId);
  const [selected, setSelected] = useState<Match | null>(null);

  if (kid.isLoading || matches.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kid.isError || matches.isError) {
    return (
      <ErrorBanner
        message="Failed to load matches"
        onRetry={() => {
          kid.refetch();
          matches.refetch();
        }}
      />
    );
  }
  if (!kid.data || !matches.data) return null;

  const groups = groupByUrgency(matches.data);
  const total = matches.data.length;
  const truncated = total >= 200;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{kid.data.name} — matches</h1>
        <p className="text-sm text-muted-foreground">{total} matches</p>
      </header>
      {total === 0 && <EmptyState>No matches yet for {kid.data.name}.</EmptyState>}
      <UrgencyGroup
        title="Registration opens this week"
        matches={groups['opens-this-week']}
        urgent
        onSelect={setSelected}
      />
      <UrgencyGroup
        title="Starting in ≤ 14 days"
        matches={groups['starting-soon']}
        onSelect={setSelected}
      />
      <UrgencyGroup
        title="Later this season"
        matches={groups['later']}
        defaultOpen={false}
        onSelect={setSelected}
      />
      {truncated && (
        <p className="text-xs text-muted-foreground">
          Showing first 200 matches. Pagination arrives in 5b.
        </p>
      )}
      <MatchDetailDrawer
        match={selected}
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
      />
    </div>
  );
}
