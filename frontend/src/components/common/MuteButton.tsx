import { useState } from 'react';
import { format } from 'date-fns';
import { Popover } from 'radix-ui';
import { Button } from '@/components/ui/button';
import { isMuted, muteUntilFromDuration, type MuteDuration } from '@/lib/mute';
import { cn } from '@/lib/utils';

interface MuteButtonProps {
  mutedUntil: string | null;
  onChange: (mutedUntil: string | null) => void;
  isPending?: boolean;
  size?: 'default' | 'sm';
}

const DURATION_OPTIONS: Array<{ value: MuteDuration; label: string }> = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: 'forever', label: 'Forever' },
];

export function MuteButton({
  mutedUntil,
  onChange,
  isPending,
  size = 'default',
}: MuteButtonProps) {
  const [open, setOpen] = useState(false);
  const muted = isMuted(mutedUntil);
  const label = muted
    ? `Muted until ${format(new Date(mutedUntil!), 'MMM d')}`
    : 'Mute';

  const handle = (next: string | null) => {
    setOpen(false);
    onChange(next);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          size={size}
          variant={muted ? 'outline' : 'ghost'}
          disabled={isPending}
        >
          {label}
        </Button>
      </Popover.Trigger>
      <Popover.Content
        className={cn(
          'z-50 rounded-md border border-border bg-popover p-1 shadow-md',
          'min-w-[10rem] text-sm',
        )}
        sideOffset={4}
        align="end"
      >
        {muted ? (
          <button
            role="menuitem"
            type="button"
            className="block w-full text-left px-2 py-1.5 rounded hover:bg-accent"
            onClick={() => handle(null)}
          >
            Unmute
          </button>
        ) : (
          DURATION_OPTIONS.map(({ value, label: dLabel }) => (
            <button
              key={value}
              role="menuitem"
              type="button"
              className="block w-full text-left px-2 py-1.5 rounded hover:bg-accent"
              onClick={() => handle(muteUntilFromDuration(value))}
            >
              {dLabel}
            </button>
          ))
        )}
      </Popover.Content>
    </Popover.Root>
  );
}
