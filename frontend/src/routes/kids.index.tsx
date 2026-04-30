import { createFileRoute, Link } from '@tanstack/react-router';
import { useKids } from '@/lib/queries';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { differenceInYears } from 'date-fns';

export const Route = createFileRoute('/kids/')({ component: KidsIndexPage });

export function KidsIndexPage() {
  const { data: kids, isLoading } = useKids();

  if (isLoading) return <Skeleton className="h-32 w-full" />;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Kids</h1>
        <Button asChild>
          <Link to="/kids/new">Add kid</Link>
        </Button>
      </div>
      {(!kids || kids.length === 0) ? (
        <div className="text-muted-foreground text-sm">
          No kids yet — Add your first kid to start matching.
        </div>
      ) : (
        <ul className="space-y-2">
          {kids.map((k) => (
            <li key={k.id} className="rounded-md border border-border p-3 flex items-center justify-between">
              <Link to="/kids/$id/matches" params={{ id: String(k.id) }} className="flex-1">
                <div className="font-medium">{k.name}</div>
                <div className="text-xs text-muted-foreground">
                  {differenceInYears(new Date(), new Date(k.dob))} years old
                  {k.active === false && ' · Inactive'}
                </div>
              </Link>
              <Link to="/kids/$id/edit" params={{ id: String(k.id) }} aria-label={`Edit ${k.name}`}>
                ✏️
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
