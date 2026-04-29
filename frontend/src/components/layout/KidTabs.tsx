import { Link, useLocation } from '@tanstack/react-router';
import { cn } from '@/lib/utils';

const tabs = [
  { to: '/kids/$id/matches', label: 'Matches' },
  { to: '/kids/$id/watchlist', label: 'Watchlist' },
  { to: '/kids/$id/calendar', label: 'Calendar' },
] as const;

export function KidTabs({ kidId }: { kidId: number }) {
  const loc = useLocation();
  return (
    <nav className="border-b border-border flex gap-2 mb-4">
      {tabs.map((t) => {
        const active = loc.pathname.endsWith(`/${t.label.toLowerCase()}`);
        return (
          <Link
            key={t.to}
            to={t.to}
            params={{ id: String(kidId) }}
            className={cn(
              'px-3 py-2 text-sm border-b-2 -mb-px',
              active ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
