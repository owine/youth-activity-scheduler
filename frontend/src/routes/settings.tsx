import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { Card } from '@/components/ui/card';
import { useAlertRouting, useHousehold } from '@/lib/queries';

export const Route = createFileRoute('/settings')({ component: SettingsPage });

function SettingsPage() {
  const hh = useHousehold();
  const routing = useAlertRouting();

  if (hh.isLoading || routing.isLoading) return <Skeleton className="h-64 w-full" />;
  if (hh.isError || routing.isError || !hh.data || !routing.data) {
    return <ErrorBanner message="Failed to load settings" onRetry={() => { hh.refetch(); routing.refetch(); }} />;
  }

  const h = hh.data;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Settings</h1>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Household</h2>
        <Card className="p-4 space-y-2 text-sm">
          <Row k="Home address" v={h.home_address ?? '—'} />
          <Row k="Home location name" v={h.home_location_name ?? '—'} />
          <Row k="Default max distance (mi)" v={h.default_max_distance_mi?.toString() ?? '—'} />
          <Row k="Digest time" v={h.digest_time} />
          <Row k="Quiet hours" v={h.quiet_hours_start && h.quiet_hours_end ? `${h.quiet_hours_start} – ${h.quiet_hours_end}` : '—'} />
          <Row k="Daily LLM cost cap" v={`$${h.daily_llm_cost_cap_usd.toFixed(2)}`} />
        </Card>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Alert routing</h2>
        <Card className="p-4">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr><th className="py-1">Type</th><th>Channels</th><th>Enabled</th></tr>
            </thead>
            <tbody>
              {routing.data.map((r) => (
                <tr key={r.type} className="border-t border-border">
                  <td className="py-1">{r.type}</td>
                  <td>{r.channels.join(', ') || '—'}</td>
                  <td>{r.enabled ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Notifier configuration</h2>
        <Card className="p-4 text-sm text-muted-foreground">
          Channel configuration available in Phase 5b.
        </Card>
      </section>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex">
      <dt className="w-48 text-muted-foreground">{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}
