import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useResendAlert } from '@/lib/mutations';
import { relDate } from '@/lib/format';
import type { Alert } from '@/lib/types';

interface Props {
  alert: Alert;
  selected?: boolean;
  onToggleSelect?: (id: number) => void;
}

export function OutboxRow({ alert, selected, onToggleSelect }: Props) {
  const resend = useResendAlert();
  const [pillState, setPillState] = useState<'idle' | 'ok' | 'err'>('idle');
  const [pillDetail, setPillDetail] = useState<string>('');

  const handleResend = async () => {
    setPillState('idle');
    try {
      await resend.mutateAsync({ alertId: alert.id });
      setPillState('ok');
      setPillDetail('Resend queued');
    } catch (err) {
      setPillState('err');
      setPillDetail(`Failed: ${(err as Error).message}`);
    }
    // Auto-clear after 3s
    setTimeout(() => setPillState('idle'), 3000);
  };

  let statusText: string;
  if (alert.closed_at) statusText = `closed (${alert.close_reason ?? 'unknown'})`;
  else if (alert.skipped) statusText = 'skipped';
  else if (alert.sent_at) statusText = `sent ${relDate(alert.sent_at)}`;
  else statusText = 'pending';

  return (
    <Card className="p-3 space-y-1">
      <div className="flex items-center gap-2">
        {onToggleSelect && (
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={() => onToggleSelect(alert.id)}
            aria-label={`Select alert ${alert.id}`}
            disabled={alert.closed_at !== null}
          />
        )}
        <Badge variant="secondary">{alert.type}</Badge>
        <div className="flex-1 text-sm">{alert.summary_text}</div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleResend}
          disabled={resend.isPending}
        >
          {resend.isPending ? 'Resending…' : 'Resend'}
        </Button>
        {pillState === 'ok' && (
          <span className="rounded bg-green-100 px-2 py-1 text-xs text-green-800 dark:bg-green-900/30 dark:text-green-300">
            {pillDetail}
          </span>
        )}
        {pillState === 'err' && (
          <span className="rounded bg-destructive/10 px-2 py-1 text-xs text-destructive">
            {pillDetail}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        {relDate(alert.scheduled_for)} · {statusText} · {alert.channels.join(', ') || '—'}
      </div>
    </Card>
  );
}
