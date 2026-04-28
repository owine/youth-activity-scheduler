import { Link } from '@tanstack/react-router';
import type { InboxKidMatchCount } from '@/lib/types';
import { EmptyState } from '@/components/common/EmptyState';

export function NewMatchesByKidSection({ rows }: { rows: InboxKidMatchCount[] }) {
  return (
    <section aria-labelledby="matches-heading" className="space-y-2">
      <h2 id="matches-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        New matches
      </h2>
      {rows.length === 0 ? (
        <EmptyState>No new matches in this window.</EmptyState>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {rows.map((r) => (
            <li key={r.kid_id}>
              <Link
                to="/kids/$id/matches"
                params={{ id: String(r.kid_id) }}
                className="block rounded-md border border-border p-3 hover:bg-accent transition"
              >
                <div className="font-semibold">{r.kid_name}</div>
                <div className="text-sm text-muted-foreground">
                  {r.total_new} new · {r.opening_soon_count} opening soon
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
