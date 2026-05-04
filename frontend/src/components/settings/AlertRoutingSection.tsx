import { useMemo } from 'react';
import { useHousehold, useAlertRouting } from '@/lib/queries';
import { useUpdateAlertRouting } from '@/lib/mutations';
import type { AlertRouting } from '@/lib/types';

export function AlertRoutingSection() {
  const household = useHousehold();
  const routing = useAlertRouting();
  const updateMutation = useUpdateAlertRouting();

  const configuredChannels = useMemo(() => {
    if (!household.data) return { email: false, ntfy: false, pushover: false };
    return {
      email: household.data.email_configured,
      ntfy: household.data.ntfy_configured,
      pushover: household.data.pushover_configured,
    };
  }, [household.data]);

  if (!routing.data) {
    return null;
  }

  const channels = ['email', 'ntfy', 'pushover'] as const;

  const handleEnabledToggle = (type: string, enabled: boolean) => {
    updateMutation.mutate({
      type,
      patch: { enabled },
    });
  };

  const handleChannelToggle = (row: AlertRouting, channel: string) => {
    // Guard: last-remaining channel in an enabled row cannot be removed
    if (row.enabled && row.channels.length === 1 && row.channels.includes(channel)) {
      return; // No mutation
    }

    const nextChannels = row.channels.includes(channel)
      ? row.channels.filter((c) => c !== channel)
      : [...row.channels, channel];

    updateMutation.mutate({
      type: row.type,
      patch: { channels: nextChannels },
    });
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Alert Routing</h2>
      <div className="overflow-x-auto">
        <table className="border-collapse border border-border w-full">
          <thead>
            <tr className="bg-muted">
              <th className="border border-border px-4 py-2 text-left font-semibold">Alert Type</th>
              <th className="border border-border px-4 py-2 text-left font-semibold">Enabled</th>
              {channels.map((ch) => (
                <th key={ch} className="border border-border px-4 py-2 text-left font-semibold">
                  {ch}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {routing.data.map((row) => (
              <tr key={row.type} className="hover:bg-muted">
                <td className="border border-border px-4 py-2">{row.type}</td>
                <td className="border border-border px-4 py-2">
                  <input
                    type="checkbox"
                    aria-label={`${row.type} enabled`}
                    checked={row.enabled}
                    onChange={(e) => handleEnabledToggle(row.type, e.target.checked)}
                    className="cursor-pointer"
                  />
                </td>
                {channels.map((ch) => {
                  const isConfigured = configuredChannels[ch as keyof typeof configuredChannels];
                  const isChecked = row.channels.includes(ch);
                  const isLastChannel = row.enabled && row.channels.length === 1 && isChecked;
                  // Disable when not configured OR when removing this channel
                  // would orphan the row (enabled with no destinations). The
                  // user disables a row entirely via the Enabled toggle.
                  // (Earlier attempt with onClick.preventDefault was racey
                  // under some library timings; disabled is bulletproof.)
                  const disabled = !isConfigured || isLastChannel;

                  return (
                    <td key={`${row.type}-${ch}`} className="border border-border px-4 py-2">
                      <input
                        type="checkbox"
                        aria-label={`${row.type} ${ch}`}
                        checked={isChecked}
                        disabled={disabled}
                        onChange={() => handleChannelToggle(row, ch)}
                        title={
                          !isConfigured
                            ? `Configure ${ch} first`
                            : isLastChannel
                              ? 'Use Enabled toggle to disable this alert type entirely'
                              : undefined
                        }
                        className={disabled ? 'cursor-not-allowed' : 'cursor-pointer'}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground italic">
        Uncheck Enabled to disable a row entirely. The last channel can't be removed individually.
      </p>
    </div>
  );
}
