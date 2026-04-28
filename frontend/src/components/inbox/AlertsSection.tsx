import { useState } from 'react';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import { EmptyState } from '@/components/common/EmptyState';

export function AlertsSection({ alerts }: { alerts: InboxAlert[] }) {
  const [selected, setSelected] = useState<InboxAlert | null>(null);

  return (
    <section aria-labelledby="alerts-heading" className="space-y-2">
      <h2 id="alerts-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        Alerts ({alerts.length})
      </h2>
      {alerts.length === 0 ? (
        <EmptyState>No alerts this week. Quiet is good.</EmptyState>
      ) : (
        <ul className="space-y-1.5">
          {alerts.map((a) => (
            <li
              key={a.id}
              className="rounded-md border border-border p-3 cursor-pointer hover:bg-accent transition"
              onClick={() => setSelected(a)}
            >
              <div className="flex items-start gap-3">
                <AlertTypeBadge type={a.type} />
                <span className="flex-1 text-sm">{a.summary_text}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <AlertDetailDrawer
        alert={selected}
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
      />
    </section>
  );
}
