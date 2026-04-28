import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { fmt } from '@/lib/format';

export function AlertDetailDrawer({
  alert,
  open,
  onOpenChange,
}: {
  alert: InboxAlert | null;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        {alert && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <AlertTypeBadge type={alert.type} /> {alert.kid_name ?? '—'}
              </SheetTitle>
              <SheetDescription>{alert.summary_text}</SheetDescription>
            </SheetHeader>
            <dl className="mt-6 space-y-2 text-sm">
              <div>
                <dt className="text-muted-foreground">Scheduled for</dt>
                <dd>{fmt(alert.scheduled_for)}</dd>
              </div>
              {alert.sent_at && (
                <div>
                  <dt className="text-muted-foreground">Sent at</dt>
                  <dd>{fmt(alert.sent_at)}</dd>
                </div>
              )}
              <div>
                <dt className="text-muted-foreground">Channels</dt>
                <dd>{alert.channels.join(', ') || '—'}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd>{alert.skipped ? 'Skipped' : alert.sent_at ? 'Sent' : 'Pending'}</dd>
              </div>
            </dl>
            <pre className="mt-6 text-xs bg-muted p-3 rounded-md overflow-auto">
              {JSON.stringify(alert.payload_json, null, 2)}
            </pre>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
