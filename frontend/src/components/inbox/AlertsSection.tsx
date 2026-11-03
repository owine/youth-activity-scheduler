import { useState } from 'react';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import { EmptyState } from '@/components/common/EmptyState';
import { RowTitleButton } from '@/components/common/RowTitleButton';

export function AlertsSection({
  alerts,
  includeClosed: includeClosedProp,
  onIncludeClosedChange,
}: {
  alerts: InboxAlert[];
  /** Controlled value. The inbox owns it, since toggling refetches the summary. */
  includeClosed?: boolean;
  onIncludeClosedChange?: (b: boolean) => void;
}) {
  const [selected, setSelected] = useState<InboxAlert | null>(null);
  const [includeClosedState, setIncludeClosed] = useState(false);
  const includeClosed = includeClosedProp ?? includeClosedState;

  return (
    <section aria-labelledby="alerts-heading" className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 id="alerts-heading" className="text-xs font-semibold uppercase text-muted-foreground">
          Alerts ({alerts.length})
        </h2>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(e) => {
              setIncludeClosed(e.target.checked);
              onIncludeClosedChange?.(e.target.checked);
            }}
          />
          Show closed
        </label>
      </div>
      {alerts.length === 0 ? (
        <EmptyState>No alerts this week. Quiet is good.</EmptyState>
      ) : (
        <ul className="space-y-1.5">
          {alerts.map((a) => {
            const isClosed = a.closed_at != null;
            return (
              <li
                key={a.id}
                className={`rounded-md border border-border p-3 cursor-pointer hover:bg-accent transition ${
                  isClosed ? 'opacity-60' : ''
                }`}
                onClick={() => setSelected(a)}
              >
                <div className="flex items-start gap-3">
                  <AlertTypeBadge type={a.type} />
                  <RowTitleButton onClick={() => setSelected(a)} className="flex-1 text-sm">
                    {a.summary_text}
                  </RowTitleButton>
                  {isClosed && (
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground border border-border rounded px-1.5 py-0.5">
                      Closed
                    </span>
                  )}
                </div>
              </li>
            );
          })}
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
