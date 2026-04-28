import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import type { Match } from '@/lib/types';
import { price, relDate } from '@/lib/format';

export function MatchDetailDrawer({
  match,
  open,
  onOpenChange,
}: {
  match: Match | null;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        {match && (
          <>
            <SheetHeader>
              <SheetTitle>{match.offering.name}</SheetTitle>
              <SheetDescription>{match.offering.site_name}</SheetDescription>
            </SheetHeader>
            <dl className="mt-6 space-y-2 text-sm">
              <div>
                <dt className="text-muted-foreground">Score</dt>
                <dd>{match.score.toFixed(2)}</dd>
              </div>
              {match.offering.start_date && (
                <div>
                  <dt className="text-muted-foreground">Starts</dt>
                  <dd>{relDate(match.offering.start_date)}</dd>
                </div>
              )}
              {match.offering.price_cents != null && (
                <div>
                  <dt className="text-muted-foreground">Price</dt>
                  <dd>{price(match.offering.price_cents / 100)}</dd>
                </div>
              )}
            </dl>
            <h3 className="mt-6 mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Match reasons
            </h3>
            <pre className="text-xs bg-muted p-3 rounded-md overflow-auto">
              {JSON.stringify(match.reasons, null, 2)}
            </pre>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
