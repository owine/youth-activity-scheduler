import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { Match } from '@/lib/types';
import { MatchCard } from './MatchCard';

export function UrgencyGroup({
  title,
  matches,
  defaultOpen = true,
  urgent = false,
  onSelect,
}: {
  title: string;
  matches: Match[];
  defaultOpen?: boolean;
  urgent?: boolean;
  onSelect: (m: Match) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (matches.length === 0) return null;

  return (
    <section className="space-y-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title} ({matches.length})
      </button>
      {open && (
        <div className="space-y-2">
          {matches.map((m) => (
            <MatchCard
              key={`${m.kid_id}-${m.offering_id}`}
              match={m}
              urgent={urgent}
              onClick={() => onSelect(m)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
