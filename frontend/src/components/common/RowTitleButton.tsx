import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/**
 * The primary title of a clickable list row, as a real button so the row's
 * drawer can be opened from the keyboard (Tab, then Enter or Space). The row
 * itself keeps its onClick for mouse users; this stops propagation so a click
 * on the title doesn't fire the handler twice.
 */
export function RowTitleButton({
  onClick,
  className,
  children,
}: {
  onClick: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cn(
        'rounded-sm text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
        className,
      )}
    >
      {children}
    </button>
  );
}
