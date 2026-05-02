import { Link, useParams } from '@tanstack/react-router';
import { useKids } from '@/lib/queries';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export function KidSwitcher() {
  const { data, isLoading, isError } = useKids();
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;

  if (isLoading) return <Skeleton className="h-7 w-32" />;
  if (isError || !data || data.length === 0) return null;

  return (
    <nav aria-label="Switch kid" className="flex gap-1">
      {data
        .filter((k) => k.active)
        .map((k) => (
          <Link
            key={k.id}
            to="/kids/$id/matches"
            params={{ id: String(k.id) }}
            className={cn(
              'rounded-md px-3 py-1 text-sm transition',
              String(k.id) === activeId
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {k.name}
          </Link>
        ))}
    </nav>
  );
}
