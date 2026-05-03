import { useState } from 'react';
import { formErrorMessage } from '@/lib/formError';
import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { TestSendButton } from './TestSendButton';
import { useUpdateHousehold } from '@/lib/mutations';
import { ApiError } from '@/lib/api';
import type { PushoverConfig } from '@/lib/types';

const pushoverSchema = z.object({
  user_key_env: z.string().min(1, 'User key env var is required'),
  app_token_env: z.string().min(1, 'App token env var is required'),
  devices: z.string(),
  emergency_retry_s: z.number().int().min(30),
  emergency_expire_s: z.number().int().min(60),
});

export function PushoverChannelSection() {
  const update = useUpdateHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showDisableConfirm, setShowDisableConfirm] = useState(false);

  const form = useForm({
    defaultValues: {
      user_key_env: '',
      app_token_env: '',
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
          user_key_env: value.user_key_env,
          app_token_env: value.app_token_env,
          ...(devices.length > 0 ? { devices } : {}),
          emergency_retry_s: value.emergency_retry_s,
          emergency_expire_s: value.emergency_expire_s,
        };
        await update.mutateAsync({ pushover_config_json: config });
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
          name="user_key_env"
          children={(field) => (
            <div>
              <label htmlFor="user_key_env" className="block text-sm font-medium">
                User Key Env
              </label>
              <input
                id="user_key_env"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="e.g. YAS_PUSHOVER_USER_KEY"
              />
              {field.state.meta.errors.map((err, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {formErrorMessage(err)}
                </p>
              ))}
              <span className="text-xs text-muted-foreground">
                e.g. YAS_PUSHOVER_USER_KEY — set this env var in your .env
              </span>
            </div>
          )}
        />

        <form.Field
          name="app_token_env"
          children={(field) => (
            <div>
              <label htmlFor="app_token_env" className="block text-sm font-medium">
                App Token Env
              </label>
              <input
                id="app_token_env"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="e.g. YAS_PUSHOVER_APP_TOKEN"
              />
              {field.state.meta.errors.map((err, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {formErrorMessage(err)}
                </p>
              ))}
              <span className="text-xs text-muted-foreground">
                e.g. YAS_PUSHOVER_APP_TOKEN — set this env var in your .env
              </span>
            </div>
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

        {/* Action buttons */}
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
