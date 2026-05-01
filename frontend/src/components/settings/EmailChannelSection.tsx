import { useState } from 'react';
import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { TestSendButton } from './TestSendButton';
import { useUpdateHousehold } from '@/lib/mutations';
import { ApiError } from '@/lib/api';
import type { SmtpConfig, ForwardEmailConfig } from '@/lib/types';

// Zod schemas for smtp and forwardemail transports
const smtpSchema = z.object({
  transport: z.literal('smtp'),
  host: z.string().min(1, 'Host is required'),
  port: z.number().int().min(1).max(65535),
  username: z.string(),
  password_env: z.string(),
  use_tls: z.boolean(),
  from_addr: z.string().email('Valid email required'),
  to_addrs: z.string().min(1, 'At least one recipient required'),
  api_token_env: z.string(),
});

const forwardEmailSchema = z.object({
  transport: z.literal('forwardemail'),
  host: z.string(),
  port: z.number(),
  username: z.string(),
  password_env: z.string(),
  use_tls: z.boolean(),
  api_token_env: z.string().min(1, 'API token env var required'),
  from_addr: z.string().email('Valid email required'),
  to_addrs: z.string().min(1, 'At least one recipient required'),
});

const schema = z.discriminatedUnion('transport', [smtpSchema, forwardEmailSchema]);

export function EmailChannelSection() {
  const update = useUpdateHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showDisableConfirm, setShowDisableConfirm] = useState(false);

  // Note: Household does NOT expose smtp_config_json (only HouseholdSettings row has it).
  // The backend makes *_config_json write-only. So we always start with empty form.
  // This is a real constraint: form starts empty/default each time page loads; users
  // must re-enter config when editing. The Disable button still works (PATCHes null).
  const form = useForm({
    defaultValues: {
      transport: 'smtp',
      host: '',
      port: 587,
      username: '',
      password_env: '',
      use_tls: true,
      from_addr: '',
      to_addrs: '',
      api_token_env: '',
    },
    validators: { onChange: schema, onMount: schema },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        // Parse to_addrs from comma-separated string to array, trimming and filtering
        const to_addrs = value.to_addrs
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean);

        let config: SmtpConfig | ForwardEmailConfig;

        if (value.transport === 'smtp') {
          config = {
            transport: 'smtp',
            host: value.host,
            port: value.port,
            use_tls: value.use_tls,
            from_addr: value.from_addr,
            to_addrs,
            // Omit username when blank — never send empty string
            ...(value.username?.trim() ? { username: value.username.trim() } : {}),
            // Omit password_env when blank
            ...(value.password_env?.trim() ? { password_env: value.password_env.trim() } : {}),
          };
        } else {
          config = {
            transport: 'forwardemail',
            api_token_env: value.api_token_env,
            from_addr: value.from_addr,
            to_addrs,
          };
        }

        await update.mutateAsync({ smtp_config_json: config });
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(detail ?? (err as Error).message);
      }
    },
  });

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Email Channel</h2>
      {errorMsg && <ErrorBanner message={errorMsg} />}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          form.handleSubmit();
        }}
        className="space-y-3 max-w-xl"
      >
        {/* Transport selector */}
        <form.Field
          name="transport"
          children={(field) => (
            <div>
              <label htmlFor="transport" className="block text-sm font-medium">
                Transport
              </label>
              <select
                id="transport"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value as 'smtp' | 'forwardemail')}
                onBlur={field.handleBlur}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              >
                <option value="smtp">SMTP</option>
                <option value="forwardemail">ForwardEmail</option>
              </select>
            </div>
          )}
        />

        {/* Conditional rendering based on transport */}
        <form.Subscribe selector={(s) => s.values.transport}>
          {(transport) => (
            <>
              {transport === 'smtp' ? (
                <>
                  <form.Field
                    name="host"
                    children={(field) => (
                      <div>
                        <label htmlFor="host" className="block text-sm font-medium">
                          SMTP Host
                        </label>
                        <input
                          id="host"
                          type="text"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(e.target.value)}
                          onBlur={field.handleBlur}
                          aria-invalid={field.state.meta.errors.length > 0}
                          className="mt-1 block w-full rounded border border-input px-3 py-2"
                          placeholder="smtp.example.com"
                        />
                        {field.state.meta.errors.map((err, i) => (
                          <p key={i} className="mt-1 text-xs text-destructive">
                            {String(err)}
                          </p>
                        ))}
                      </div>
                    )}
                  />

                  <form.Field
                    name="port"
                    children={(field) => (
                      <div>
                        <label htmlFor="port" className="block text-sm font-medium">
                          SMTP Port
                        </label>
                        <input
                          id="port"
                          type="number"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(Number(e.target.value))}
                          onBlur={field.handleBlur}
                          aria-invalid={field.state.meta.errors.length > 0}
                          className="mt-1 block w-full rounded border border-input px-3 py-2"
                          min="1"
                          max="65535"
                        />
                        {field.state.meta.errors.map((err, i) => (
                          <p key={i} className="mt-1 text-xs text-destructive">
                            {String(err)}
                          </p>
                        ))}
                      </div>
                    )}
                  />

                  <form.Field
                    name="username"
                    children={(field) => (
                      <div>
                        <label htmlFor="username" className="block text-sm font-medium">
                          Username (optional)
                        </label>
                        <input
                          id="username"
                          type="text"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(e.target.value)}
                          onBlur={field.handleBlur}
                          className="mt-1 block w-full rounded border border-input px-3 py-2"
                          placeholder="Optional; omitted if blank"
                        />
                      </div>
                    )}
                  />

                  <form.Field
                    name="password_env"
                    children={(field) => (
                      <div>
                        <label htmlFor="password_env" className="block text-sm font-medium">
                          Password Env Var (optional)
                        </label>
                        <input
                          id="password_env"
                          type="text"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(e.target.value)}
                          onBlur={field.handleBlur}
                          className="mt-1 block w-full rounded border border-input px-3 py-2"
                          placeholder="e.g. YAS_SMTP_PASSWORD"
                        />
                        <span className="text-xs text-muted-foreground">
                          e.g. YAS_SMTP_PASSWORD — set this env var in your .env
                        </span>
                      </div>
                    )}
                  />

                  <form.Field
                    name="use_tls"
                    children={(field) => (
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={field.state.value}
                          onChange={(e) => field.handleChange(e.target.checked)}
                          className="rounded"
                        />
                        <span className="text-sm font-medium">Use TLS</span>
                      </label>
                    )}
                  />
                </>
              ) : (
                <form.Field
                  name="api_token_env"
                  children={(field) => (
                    <div>
                      <label htmlFor="api_token_env" className="block text-sm font-medium">
                        ForwardEmail API Token
                      </label>
                      <input
                        id="api_token_env"
                        type="text"
                        value={field.state.value}
                        onChange={(e) => field.handleChange(e.target.value)}
                        onBlur={field.handleBlur}
                        aria-invalid={field.state.meta.errors.length > 0}
                        className="mt-1 block w-full rounded border border-input px-3 py-2"
                        placeholder="e.g. YAS_FORWARDEMAIL_TOKEN"
                      />
                      {field.state.meta.errors.map((err, i) => (
                        <p key={i} className="mt-1 text-xs text-destructive">
                          {String(err)}
                        </p>
                      ))}
                      <span className="text-xs text-muted-foreground">
                        e.g. YAS_FORWARDEMAIL_TOKEN — set this env var in your .env
                      </span>
                    </div>
                  )}
                />
              )}
            </>
          )}
        </form.Subscribe>

        {/* Shared from_addr and to_addrs fields */}
        <form.Field
          name="from_addr"
          children={(field) => (
            <div>
              <label htmlFor="from_addr" className="block text-sm font-medium">
                From Address
              </label>
              <input
                id="from_addr"
                type="email"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="noreply@example.com"
              />
              {field.state.meta.errors.map((err, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {String(err)}
                </p>
              ))}
            </div>
          )}
        />

        <form.Field
          name="to_addrs"
          children={(field) => (
            <div>
              <label htmlFor="to_addrs" className="block text-sm font-medium">
                To Addresses (comma-separated)
              </label>
              <input
                id="to_addrs"
                type="text"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
                placeholder="admin@example.com, support@example.com"
              />
              {field.state.meta.errors.map((err, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {String(err)}
                </p>
              ))}
            </div>
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

          <TestSendButton channel="email" label="Send test email" dirty={form.state.isDirty} />

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
        title="Disable email channel?"
        description="Existing alert routing entries pointing to email will be cleared."
        confirmLabel="Disable"
        destructive
        onConfirm={async () => {
          setShowDisableConfirm(false);
          try {
            setErrorMsg(null);
            await update.mutateAsync({ smtp_config_json: null });
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
