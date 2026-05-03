import { useState } from 'react';
import { formErrorMessage } from '@/lib/formError';
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
import type { NtfyConfig } from '@/lib/types';

const ntfySchema = z.object({
  base_url: z.string().url(),
  topic: z.string().min(1, 'Topic is required'),
  auth_token_value: z.string(),
});

export function NtfyChannelSection() {
  const update = useUpdateHousehold();
  const household = useHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showDisableConfirm, setShowDisableConfirm] = useState(false);

  const authStatus = household.data?.credential_status?.['ntfy_auth_token'];

  const form = useForm({
    defaultValues: {
      base_url: 'https://ntfy.sh',
      topic: '',
      auth_token_value: '',
    },
    validators: { onChange: ntfySchema, onMount: ntfySchema },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        const config: NtfyConfig = {
          base_url: value.base_url,
          topic: value.topic,
          ...(value.auth_token_value?.trim()
            ? { auth_token_value: value.auth_token_value.trim() }
            : {}),
        };
        await update.mutateAsync({ ntfy_config_json: config });
        form.setFieldValue('auth_token_value', '');
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(detail ?? (err as Error).message);
      }
    },
  });

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Ntfy Channel</h2>
      {errorMsg && <ErrorBanner message={errorMsg} />}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          form.handleSubmit();
        }}
        className="space-y-3 max-w-xl"
      >
        <form.Field
          name="base_url"
          children={(field) => (
            <div>
              <label htmlFor="base_url" className="block text-sm font-medium">
                Base URL
              </label>
              <input
                id="base_url"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="https://ntfy.sh"
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
          name="topic"
          children={(field) => (
            <div>
              <label htmlFor="topic" className="block text-sm font-medium">
                Topic
              </label>
              <input
                id="topic"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="my-alerts"
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
          name="auth_token_value"
          children={(field) => (
            <CredentialField
              id="auth_token_value"
              label="Auth Token (optional)"
              hint="Anonymous if blank and no env var set."
              value={field.state.value}
              onChange={field.handleChange}
              onBlur={field.handleBlur}
              status={authStatus}
              errors={field.state.meta.errors.map(formErrorMessage)}
            />
          )}
        />

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
            {(dirty) => <TestSendButton channel="ntfy" label="Send test ntfy" dirty={dirty} />}
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
        title="Disable ntfy channel?"
        description="Existing alert routing entries pointing to ntfy will be cleared."
        confirmLabel="Disable"
        destructive
        onConfirm={async () => {
          setShowDisableConfirm(false);
          try {
            setErrorMsg(null);
            await update.mutateAsync({ ntfy_config_json: null });
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
