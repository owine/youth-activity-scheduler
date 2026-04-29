import { Badge } from '@/components/ui/badge';

const tone: Record<string, 'default' | 'secondary' | 'destructive' | 'outline-solid'> = {
  watchlist_hit: 'destructive',
  reg_opens_now: 'destructive',
  reg_opens_1h: 'destructive',
  reg_opens_24h: 'default',
  new_match: 'secondary',
  schedule_posted: 'outline-solid',
  crawl_failed: 'destructive',
  site_stagnant: 'outline-solid',
  no_matches_for_kid: 'outline-solid',
  push_cap: 'outline-solid',
  digest: 'secondary',
};

export function AlertTypeBadge({ type }: { type: string }) {
  return <Badge variant={tone[type] ?? 'outline-solid'}>{type}</Badge>;
}
