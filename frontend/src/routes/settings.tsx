import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useAlertRouting, useHousehold } from '@/lib/queries';
import { HouseholdSection } from '@/components/settings/HouseholdSection';
import { EmailChannelSection } from '@/components/settings/EmailChannelSection';
import { NtfyChannelSection } from '@/components/settings/NtfyChannelSection';
import { PushoverChannelSection } from '@/components/settings/PushoverChannelSection';
import { AlertRoutingSection } from '@/components/settings/AlertRoutingSection';

export const Route = createFileRoute('/settings')({ component: SettingsPage });

function SettingsPage() {
  const hh = useHousehold();
  const routing = useAlertRouting();

  if (hh.isLoading || routing.isLoading) return <Skeleton className="h-64 w-full" />;
  if (hh.isError || routing.isError || !hh.data || !routing.data) {
    return (
      <ErrorBanner
        message="Failed to load settings"
        onRetry={() => {
          hh.refetch();
          routing.refetch();
        }}
      />
    );
  }

  return (
    <div className="max-w-3xl space-y-8">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <HouseholdSection />
      <EmailChannelSection />
      <NtfyChannelSection />
      <PushoverChannelSection />
      <AlertRoutingSection />
    </div>
  );
}
