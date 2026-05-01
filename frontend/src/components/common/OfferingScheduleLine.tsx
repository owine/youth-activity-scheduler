import type { OfferingSummary } from '@/lib/types';
import { price, relDate } from '@/lib/format';

interface Props {
  offering: OfferingSummary;
  showRegOpens?: boolean;
  now?: Date;
}

/**
 * Shared offering schedule line. Renders:
 *   site_name · starts in N days · $price [· reg in N days]
 * Used by MatchCard, OfferingRow, and EnrollmentRow.
 */
export function OfferingScheduleLine({ offering: o, showRegOpens = false, now }: Props) {
  return (
    <div className="text-sm text-muted-foreground">
      {o.site_name}
      {o.start_date && ` · starts in ${relDate(o.start_date, now)}`}
      {o.price_cents != null && ` · ${price(o.price_cents / 100)}`}
      {showRegOpens &&
        o.registration_opens_at &&
        ` · reg in ${relDate(o.registration_opens_at, now)}`}
    </div>
  );
}
