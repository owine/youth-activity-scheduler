import { Link } from '@tanstack/react-router';
import type { InboxSiteActivity } from '@/lib/types';

export function SiteActivitySection({ activity }: { activity: InboxSiteActivity }) {
  if (activity.refreshed_count + activity.posted_new_count + activity.stagnant_count === 0) {
    return null;
  }
  return (
    <section aria-labelledby="sites-heading" className="space-y-2">
      <h2 id="sites-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        Site activity
      </h2>
      <p className="text-sm text-muted-foreground">
        {activity.refreshed_count} sites refreshed · {activity.posted_new_count} posted new schedules ·{' '}
        {activity.stagnant_count > 0 ? (
          <Link to="/sites" className="underline underline-offset-2 hover:text-foreground">
            {activity.stagnant_count} stagnant
          </Link>
        ) : (
          '0 stagnant'
        )}
      </p>
    </section>
  );
}
