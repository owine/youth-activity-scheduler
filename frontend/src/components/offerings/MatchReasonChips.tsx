import type { KidBrief, OfferingRow } from '@/lib/types';
import { chipsForOffering } from '@/lib/offeringsFilters';

interface Props {
  row: OfferingRow;
  kidsById: Map<number, KidBrief>;
  now: Date;
}

export function MatchReasonChips({ row, kidsById, now }: Props) {
  const chips = chipsForOffering(row, kidsById, now);
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {chips.map((c) => (
        <span key={c.kind} role="status" className={`rounded px-2 py-0.5 text-xs ${c.className}`}>
          {c.label}
        </span>
      ))}
    </div>
  );
}
