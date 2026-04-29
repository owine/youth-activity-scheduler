import { startTransition, useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import type { CloseReason, InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { fmt } from '@/lib/format';
import { useCloseAlert, useReopenAlert } from '@/lib/mutations';

export function AlertDetailDrawer({
  alert,
  open,
  onOpenChange,
}: {
  alert: InboxAlert | null;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  const close = useCloseAlert();
  const reopen = useReopenAlert();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inFlight = close.isPending || reopen.isPending;

  // Clear any prior error when the drawer's alert changes.
  useEffect(() => {
    startTransition(() => {
      setErrorMsg(null);
    });
    close.reset();
    reopen.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert?.id]);

  if (!alert) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent />
      </Sheet>
    );
  }

  const handleClose = (reason: CloseReason) => {
    setErrorMsg(null);
    close.mutate(
      { alertId: alert.id, reason },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setErrorMsg(err.message || 'Failed to close alert'),
      },
    );
  };

  const handleReopen = () => {
    setErrorMsg(null);
    reopen.mutate(
      { alertId: alert.id },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setErrorMsg(err.message || 'Failed to reopen alert'),
      },
    );
  };

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        // Suppress user-initiated dismiss while a mutation is in-flight.
        if (inFlight && !o) return;
        onOpenChange(o);
      }}
    >
      <SheetContent>
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
            <dd>
              {alert.closed_at
                ? `Closed (${alert.close_reason}) at ${fmt(alert.closed_at)}`
                : alert.skipped
                  ? 'Skipped'
                  : alert.sent_at
                    ? 'Sent'
                    : 'Pending'}
            </dd>
          </div>
        </dl>
        <pre className="mt-6 text-xs bg-muted p-3 rounded-md overflow-auto">
          {JSON.stringify(alert.payload_json, null, 2)}
        </pre>

        {errorMsg && (
          <div className="mt-4">
            <ErrorBanner message={errorMsg} />
          </div>
        )}

        <div className="mt-6 flex gap-2">
          {alert.closed_at == null ? (
            <>
              <Button onClick={() => handleClose('acknowledged')} disabled={inFlight}>
                Acknowledge
              </Button>
              <Button
                variant="outline"
                onClick={() => handleClose('dismissed')}
                disabled={inFlight}
              >
                Dismiss
              </Button>
            </>
          ) : (
            <Button onClick={handleReopen} disabled={inFlight}>
              Reopen
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
