import { useState } from 'react';
import { touchedFormErrors } from '@/lib/formError';
import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useHousehold } from '@/lib/queries';
import { useUpdateHousehold } from '@/lib/mutations';
import { ApiError } from '@/lib/api';

const TIME_RX = /^\d\d:\d\d$/;

const schema = z
  .object({
    home_address: z.string(),
    home_location_name: z.string(),
    default_max_distance_mi: z.number().min(0).nullable(),
    no_distance_limit: z.boolean(),
    digest_time: z.string().regex(TIME_RX, 'HH:MM'),
    quiet_hours_start: z.string(),
    quiet_hours_end: z.string(),
    daily_llm_cost_cap_usd: z.number().min(0),
  })
  .refine(
    (v) =>
      (v.quiet_hours_start === '' && v.quiet_hours_end === '') ||
      (v.quiet_hours_start !== '' &&
        v.quiet_hours_end !== '' &&
        TIME_RX.test(v.quiet_hours_start) &&
        TIME_RX.test(v.quiet_hours_end)),
    { message: 'Set both quiet-hours times or leave both blank', path: ['quiet_hours_start'] },
  );

export function HouseholdSection() {
  const hh = useHousehold();
  const update = useUpdateHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Create form hook before checking loading state to satisfy Rules of Hooks
  const form = useForm({
    defaultValues: hh.data
      ? {
          home_address: hh.data.home_address ?? '',
          home_location_name: hh.data.home_location_name ?? '',
          default_max_distance_mi: hh.data.default_max_distance_mi,
          no_distance_limit: hh.data.default_max_distance_mi === null,
          digest_time: hh.data.digest_time,
          quiet_hours_start: hh.data.quiet_hours_start ?? '',
          quiet_hours_end: hh.data.quiet_hours_end ?? '',
          daily_llm_cost_cap_usd: hh.data.daily_llm_cost_cap_usd,
        }
      : {
          home_address: '',
          home_location_name: '',
          default_max_distance_mi: null,
          no_distance_limit: true,
          digest_time: '07:00',
          quiet_hours_start: '',
          quiet_hours_end: '',
          daily_llm_cost_cap_usd: 1.0,
        },
    validators: { onChange: schema, onMount: schema },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      const patch = {
        home_address: value.home_address.trim() || null,
        home_location_name: value.home_location_name.trim() || null,
        default_max_distance_mi: value.no_distance_limit ? null : value.default_max_distance_mi,
        digest_time: value.digest_time,
        quiet_hours_start: value.quiet_hours_start.trim() || null,
        quiet_hours_end: value.quiet_hours_end.trim() || null,
        daily_llm_cost_cap_usd: value.daily_llm_cost_cap_usd,
      };
      try {
        await update.mutateAsync(patch);
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(detail ?? (err as Error).message);
      }
    },
  });

  if (!hh.data) return null;
  const h = hh.data;

  const geocodePill = h.home_address ? (
    h.home_lat !== null && h.home_lon !== null ? (
      <span className="text-xs text-green-700 dark:text-green-300">
        📍 Geocoded: {h.home_lat.toFixed(4)}, {h.home_lon.toFixed(4)}
      </span>
    ) : (
      <span className="text-xs text-amber-700 dark:text-amber-300">
        ⚠️ Geocoding failed — distance gates will be skipped
      </span>
    )
  ) : null;

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Household</h2>
      {errorMsg && <ErrorBanner message={errorMsg} />}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          form.handleSubmit();
        }}
        className="space-y-3 max-w-xl"
      >
        <form.Field
          name="home_address"
          children={(field) => (
            <div>
              <label htmlFor="home_address" className="block text-sm font-medium">
                Home Address
              </label>
              <input
                id="home_address"
                type="text"
                value={field.state.value ?? ''}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              />
              {touchedFormErrors(field.state.meta).map((m, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {m}
                </p>
              ))}
              {geocodePill && <div className="mt-2">{geocodePill}</div>}
            </div>
          )}
        />

        <form.Field
          name="home_location_name"
          children={(field) => (
            <div>
              <label htmlFor="home_location_name" className="block text-sm font-medium">
                Home Location Name
              </label>
              <input
                id="home_location_name"
                type="text"
                value={field.state.value ?? ''}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              />
              {touchedFormErrors(field.state.meta).map((m, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {m}
                </p>
              ))}
            </div>
          )}
        />

        <div className="space-y-2">
          <form.Field
            name="default_max_distance_mi"
            children={(field) => (
              <div>
                <label htmlFor="default_max_distance_mi" className="block text-sm font-medium">
                  Default Max Distance (mi)
                </label>
                <input
                  id="default_max_distance_mi"
                  type="number"
                  value={field.state.value ?? ''}
                  onChange={(e) =>
                    field.handleChange(e.target.value ? Number(e.target.value) : null)
                  }
                  onBlur={field.handleBlur}
                  disabled={form.getFieldValue('no_distance_limit')}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="mt-1 block w-full rounded border border-input px-3 py-2"
                  min="0"
                  step="0.1"
                />
                {touchedFormErrors(field.state.meta).map((m, i) => (
                  <p key={i} className="mt-1 text-xs text-destructive">
                    {m}
                  </p>
                ))}
              </div>
            )}
          />

          <form.Field
            name="no_distance_limit"
            children={(field) => (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={field.state.value}
                  onChange={(e) => {
                    field.handleChange(e.target.checked);
                    if (e.target.checked) {
                      form.setFieldValue('default_max_distance_mi', null);
                    }
                  }}
                  className="rounded"
                />
                <span className="text-sm font-medium">No limit</span>
              </label>
            )}
          />
        </div>

        <form.Field
          name="digest_time"
          children={(field) => (
            <div>
              <label htmlFor="digest_time" className="block text-sm font-medium">
                Digest Time
              </label>
              <input
                id="digest_time"
                type="time"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              />
              {touchedFormErrors(field.state.meta).map((m, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {m}
                </p>
              ))}
            </div>
          )}
        />

        <div className="space-y-2">
          <form.Field
            name="quiet_hours_start"
            children={(field) => (
              <div>
                <label htmlFor="quiet_hours_start" className="block text-sm font-medium">
                  Quiet Hours Start
                </label>
                <input
                  id="quiet_hours_start"
                  type="time"
                  value={field.state.value ?? ''}
                  onChange={(e) => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="mt-1 block w-full rounded border border-input px-3 py-2"
                />
                {touchedFormErrors(field.state.meta).map((m, i) => (
                  <p key={i} className="mt-1 text-xs text-destructive">
                    {m}
                  </p>
                ))}
              </div>
            )}
          />

          <form.Field
            name="quiet_hours_end"
            children={(field) => (
              <div>
                <label htmlFor="quiet_hours_end" className="block text-sm font-medium">
                  Quiet Hours End
                </label>
                <input
                  id="quiet_hours_end"
                  type="time"
                  value={field.state.value ?? ''}
                  onChange={(e) => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="mt-1 block w-full rounded border border-input px-3 py-2"
                />
                {touchedFormErrors(field.state.meta).map((m, i) => (
                  <p key={i} className="mt-1 text-xs text-destructive">
                    {m}
                  </p>
                ))}
              </div>
            )}
          />
        </div>

        <form.Field
          name="daily_llm_cost_cap_usd"
          children={(field) => (
            <div>
              <label htmlFor="daily_llm_cost_cap_usd" className="block text-sm font-medium">
                Daily LLM Cost Cap (USD)
              </label>
              <div className="mt-1 flex items-center rounded border border-input">
                <span className="px-3 py-2 text-sm">$</span>
                <input
                  id="daily_llm_cost_cap_usd"
                  type="number"
                  value={field.state.value}
                  onChange={(e) => field.handleChange(Number(e.target.value))}
                  onBlur={field.handleBlur}
                  aria-invalid={field.state.meta.errors.length > 0}
                  className="flex-1 border-0 px-3 py-2 outline-none"
                  min="0"
                  step="0.5"
                />
              </div>
              {touchedFormErrors(field.state.meta).map((m, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {m}
                </p>
              ))}
            </div>
          )}
        />

        <form.Subscribe selector={(state) => state.canSubmit}>
          {(canSubmit) => (
            <Button type="submit" disabled={update.isPending || !canSubmit}>
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
          )}
        </form.Subscribe>
      </form>
    </section>
  );
}
