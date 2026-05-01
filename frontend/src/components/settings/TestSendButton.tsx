import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useTestNotifier } from '@/lib/mutations';
import type { TestSendResult } from '@/lib/types';

interface Props {
  channel: 'email' | 'ntfy' | 'pushover';
  label: string;
  dirty: boolean;
}

export function TestSendButton({ channel, label, dirty }: Props) {
  const test = useTestNotifier();
  const [result, setResult] = useState<TestSendResult | null>(null);

  const handleClick = async () => {
    setResult(null);
    try {
      const r = await test.mutateAsync({ channel });
      setResult(r);
    } catch (err) {
      setResult({ ok: false, detail: (err as Error).message });
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        onClick={handleClick}
        disabled={dirty || test.isPending}
      >
        {test.isPending ? 'Sending…' : label}
      </Button>
      {result && (
        <span
          className={
            result.ok
              ? 'rounded bg-green-100 px-2 py-1 text-xs text-green-800 dark:bg-green-900/30 dark:text-green-300'
              : 'rounded bg-destructive/10 px-2 py-1 text-xs text-destructive'
          }
        >
          {result.ok ? 'Sent ✓' : `Failed: ${result.detail}`}
        </span>
      )}
    </div>
  );
}
