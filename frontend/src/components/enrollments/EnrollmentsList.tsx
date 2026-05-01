import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { KidTabs } from '@/components/layout/KidTabs';
import { useKid, useKidEnrollments } from '@/lib/queries';
import { EnrollmentRow } from './EnrollmentRow';
import { EnrollmentEditSheet } from './EnrollmentEditSheet';
import type { Enrollment, EnrollmentStatus } from '@/lib/types';

const ACTIVE: EnrollmentStatus[] = ['interested', 'enrolled', 'waitlisted'];

export function EnrollmentsList({ kidId }: { kidId: number }) {
  const kid = useKid(kidId);
  const enrollments = useKidEnrollments(kidId);
  const [editing, setEditing] = useState<Enrollment | null>(null);
  const [pendingEnrollmentId] = useState<number | null>(null);

  if (kid.isLoading || enrollments.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kid.isError || enrollments.isError) {
    return (
      <ErrorBanner
        message="Failed to load enrollments"
        onRetry={() => {
          kid.refetch();
          enrollments.refetch();
        }}
      />
    );
  }
  if (!kid.data || !enrollments.data) return null;

  const sorted = [...enrollments.data].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const active = sorted.filter((e) => ACTIVE.includes(e.status));
  const history = sorted.filter((e) => !ACTIVE.includes(e.status));

  return (
    <div className="space-y-4">
      <KidTabs kidId={kidId} />
      <h1 className="text-2xl font-semibold">{kid.data.name} — enrollments</h1>

      {active.length === 0 && history.length === 0 ? (
        <EmptyState>
          No enrollments yet. Sign up via{' '}
          <Link to="/kids/$id/matches" params={{ id: String(kidId) }} className="underline">
            Matches
          </Link>
          .
        </EmptyState>
      ) : (
        <>
          <section>
            <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Active</h2>
            {active.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No active enrollments. Past enrollments below.
              </p>
            ) : (
              <ul className="space-y-2">
                {active.map((e) => (
                  <li key={e.id}>
                    <EnrollmentRow
                      enrollment={e}
                      kidId={kidId}
                      isPending={pendingEnrollmentId === e.id}
                      onEdit={setEditing}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
          {history.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground">
                Show {history.length} past enrollment{history.length === 1 ? '' : 's'}
              </summary>
              <ul className="mt-2 space-y-2">
                {history.map((e) => (
                  <li key={e.id}>
                    <EnrollmentRow
                      enrollment={e}
                      kidId={kidId}
                      isPending={pendingEnrollmentId === e.id}
                      onEdit={setEditing}
                    />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      <EnrollmentEditSheet enrollment={editing} kidId={kidId} onClose={() => setEditing(null)} />
    </div>
  );
}
