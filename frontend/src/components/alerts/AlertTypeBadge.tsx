import { Badge } from '@/components/ui/badge';

const tone: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  watchlist_hit: 'destructive',
  reg_opens_now: 'destructive',
  reg_opens_1h: 'destructive',
  reg_opens_24h: 'default',
  new_match: 'secondary',
  schedule_posted: 'outline',
  crawl_failed: 'destructive',
  site_stagnant: 'outline',
  no_matches_for_kid: 'outline',
  push_cap: 'outline',
  digest: 'secondary',
};

export function AlertTypeBadge({ type }: { type: string }) {
  return <Badge variant={tone[type] ?? 'outline'}>{type}</Badge>;
}
