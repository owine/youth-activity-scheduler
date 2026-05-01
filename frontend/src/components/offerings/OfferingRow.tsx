import type { KidBrief, Match, OfferingRow as OfferingRowType } from '@/lib/types';
import { Card } from '@/components/ui/card';
import { MuteButton } from '@/components/common/MuteButton';
import { OfferingScheduleLine } from '@/components/common/OfferingScheduleLine';
import { useUpdateOfferingMute } from '@/lib/mutations';
import { MatchReasonChips } from './MatchReasonChips';

interface Props {
  row: OfferingRowType;
  kidsById: Map<number, KidBrief>;
  now: Date;
  onSelect: (match: Match) => void;
}

export function OfferingRow({ row, kidsById, now, onSelect }: Props) {
  const muteOffering = useUpdateOfferingMute();
  const o = row.offering;
  const bestMatch = row.matches[0]!;

  return (
    <Card
      className="p-3 cursor-pointer hover:bg-accent transition"
      onClick={() => onSelect(bestMatch)}
    >
      {/* Top line: name, chips, score, mute button */}
      <div className="flex items-center gap-3 mb-2">
        <div className="font-semibold flex-1">{o.name}</div>
        <MatchReasonChips row={row} kidsById={kidsById} now={now} />
        <span className="text-sm font-semibold">{bestMatch.score.toFixed(2)}</span>
        <div onClick={(e) => e.stopPropagation()}>
          <MuteButton
            size="sm"
            mutedUntil={o.muted_until ?? null}
            onChange={(mutedUntil) => muteOffering.mutate({ offeringId: o.id, mutedUntil })}
            isPending={muteOffering.isPending}
          />
        </div>
      </div>

      {/* Second line: site_name, dates, price */}
      <div className="mb-1">
        <OfferingScheduleLine offering={o} now={now} />
      </div>

      {/* Third line: matched kids with scores */}
      <div className="text-xs text-muted-foreground">
        Matches:{' '}
        {row.matches
          .map((m) => `${kidsById.get(m.kid_id)?.name ?? 'Unknown'} (${m.score.toFixed(2)})`)
          .join(' · ')}
      </div>
    </Card>
  );
}
