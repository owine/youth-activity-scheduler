import type { Match } from '@/lib/types';
import { Card } from '@/components/ui/card';
import { price, relDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { MuteButton } from '@/components/common/MuteButton';
import { useUpdateOfferingMute } from '@/lib/mutations';

export function MatchCard({
  match,
  urgent,
  onClick,
}: {
  match: Match;
  urgent?: boolean;
  onClick?: () => void;
}) {
  const o = match.offering;
  const muteOffering = useUpdateOfferingMute();

  return (
    <Card
      className={cn(
        'p-3 cursor-pointer hover:bg-accent transition',
        urgent && 'border-destructive/40',
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <div className="font-semibold">{o.name}</div>
          <div className="text-sm text-muted-foreground">
            {o.site_name}
            {o.start_date && ` · ${relDate(o.start_date)}`}
            {o.price_cents != null && ` · ${price(o.price_cents / 100)}`}
            {o.registration_opens_at && ` · reg ${relDate(o.registration_opens_at)}`}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">{match.score.toFixed(2)}</span>
          {/* Stop propagation so the Mute popover doesn't also fire the
              row's onClick (which opens the MatchDetailDrawer). */}
          <div onClick={(e) => e.stopPropagation()}>
            <MuteButton
              size="sm"
              mutedUntil={o.muted_until ?? null}
              onChange={(mutedUntil) =>
                muteOffering.mutate({ offeringId: o.id, mutedUntil })
              }
              isPending={muteOffering.isPending}
            />
          </div>
        </div>
      </div>
    </Card>
  );
}
