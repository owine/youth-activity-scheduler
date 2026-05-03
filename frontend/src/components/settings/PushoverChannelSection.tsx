import { useState } from 'react';
import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { CredentialField } from './CredentialField';
import { TestSendButton } from './TestSendButton';
import { useUpdateHousehold } from '@/lib/mutations';
import { useHousehold } from '@/lib/queries';
import { ApiError } from '@/lib/api';
import { formErrorMessage } from '@/lib/formError';
import type { PushoverConfig } from '@/lib/types';

// Both credential overrides are optional — empty string means "fall back
// to the conventional env var on the server". We trust the user/UI to
// keep them blank when env is sufficient.
const pushoverSchema = z.object({
  user_key_value: z.string(),
  app_token_value: z.string(),
  devices: z.string(),
  emergency_retry_s: z.number().int().min(30),
  emergency_expire_s: z.number().int().min(60),
});

export function PushoverChannelSection() {
  const update = useUpdateHousehold();
  const household = useHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showDisableConfirm, setShowDisableConfirm] = useState(false);

  const userKeyStatus = household.data?.credential_status?.['pushover_user_key'];
  const appTokenStatus = household.data?.credential_status?.['pushover_app_token'];

  const form = useForm({
    defaultValues: {
      user_key_value: '',
      app_token_value: '',
      devices: '',
      emergency_retry_s: 60,
      emergency_expire_s: 3600,
    },
    validators: { onChange: pushoverSchema, onMount: pushoverSchema },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        const devices =
          value.devices
            ?.split(',')
            .map((s) => s.trim())
            .filter(Boolean) ?? [];
        const config: PushoverConfig = {
          // Only send *_value when the user actually typed something —
          // empty string keeps existing DB value cleared and falls back
          // to env. Sending undefined (omitted) leaves any prior DB
          // value alone since the patch endpoint replaces the whole
          // config blob; we're explicit to avoid that footgun.
          ...(value.user_key_value ? { user_key_value: value.user_key_value } : {}),
          ...(value.app_token_value ? { app_token_value: value.app_token_value } : {}),
          ...(devices.length > 0 ? { devices } : {}),
          emergency_retry_s: value.emergency_retry_s,
          emergency_expire_s: value.emergency_expire_s,
        };
        await update.mutateAsync({ pushover_config_json: config });
        // Reset secret inputs so they don't stay displayed in the DOM
        // after save. The status badge will refresh from the next query.
        form.setFieldValue('user_key_value', '');
        form.setFieldValue('app_token_value', '');
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(detail ?? (err as Error).message);
      }
    },
  });

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Pushover Channel</h2>
      {errorMsg && <ErrorBanner message={errorMsg} />}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          form.handleSubmit();
        }}
        className="space-y-3 max-w-xl"
      >
        <form.Field
          name="user_key_value"
          children={(field) => (
            <CredentialField
              id="user_key_value"
              label="User Key"
              value={field.state.value}
              onChange={field.handleChange}
              onBlur={field.handleBlur}
              status={userKeyStatus}
              errors={field.state.meta.errors.map(formErrorMessage)}
            />
          )}
        />

        <form.Field
          name="app_token_value"
          children={(field) => (
            <CredentialField
              id="app_token_value"
              label="App Token"
              value={field.state.value}
              onChange={field.handleChange}
              onBlur={field.handleBlur}
              status={appTokenStatus}
              errors={field.state.meta.errors.map(formErrorMessage)}
            />
          )}
        />

        <form.Field
          name="devices"
          children={(field) => (
            <div>
              <label htmlFor="devices" className="block text-sm font-medium">
                Devices (comma-separated, optional)
              </label>
              <input
                id="devices"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="phone, tablet, watch"
              />
            </div>
          )}
        />

        <details className="space-y-3">
          <summary className="cursor-pointer font-medium text-sm">Advanced</summary>

          <form.Field
            name="emergency_retry_s"
            children={(field) => (
              <div>
                <label htmlFor="emergency_retry_s" className="block text-sm font-medium">
                  Emergency Retry (seconds)
                </label>
                <input
                  id="emergency_retry_s"
                  type="number"
                  value={field.state.value}
                  onChange={(e) => field.handleChange(Number(e.target.value))}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="mt-1 block w-full rounded border border-input px-3 py-2"
                  min="30"
                />
                {field.state.meta.errors.map((err, i) => (
                  <p key={i} className="mt-1 text-xs text-destructive">
                    {formErrorMessage(err)}
                  </p>
                ))}
              </div>
            )}
          />

          <form.Field
            name="emergency_expire_s"
            children={(field) => (
              <div>
                <label htmlFor="emergency_expire_s" className="block text-sm font-medium">
                  Emergency Expire (seconds)
                </label>
                <input
                  id="emergency_expire_s"
                  type="number"
                  value={field.state.value}
                  onChange={(e) => field.handleChange(Number(e.target.value))}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="mt-1 block w-full rounded border border-input px-3 py-2"
                  min="60"
                />
                {field.state.meta.errors.map((err, i) => (
                  <p key={i} className="mt-1 text-xs text-destructive">
                    {formErrorMessage(err)}
                  </p>
                ))}
              </div>
            )}
          />
        </details>

        <div className="flex items-center gap-3 pt-2">
          <form.Subscribe selector={(state) => state.canSubmit}>
            {(canSubmit) => (
              <Button type="submit" disabled={update.isPending || !canSubmit}>
                {update.isPending ? 'Saving…' : 'Save'}
              </Button>
            )}
          </form.Subscribe>

          <form.Subscribe selector={(state) => state.isDirty}>
            {(dirty) => (
              <TestSendButton channel="pushover" label="Send test pushover" dirty={dirty} />
            )}
          </form.Subscribe>

          <Button
            type="button"
            variant="outline"
            onClick={() => setShowDisableConfirm(true)}
            disabled={update.isPending}
          >
            Disable channel
          </Button>
        </div>
      </form>

      <ConfirmDialog
        open={showDisableConfirm}
        onOpenChange={setShowDisableConfirm}
        title="Disable pushover channel?"
        description="Existing alert routing entries pointing to pushover will be cleared."
        confirmLabel="Disable"
        destructive
        onConfirm={async () => {
          setShowDisableConfirm(false);
          try {
            setErrorMsg(null);
            await update.mutateAsync({ pushover_config_json: null });
          } catch (err) {
            const detail =
              err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
            setErrorMsg(detail ?? (err as Error).message);
          }
        }}
      />
    </section>
  );
}
