import { useForm } from '@tanstack/react-form';
import { uniqueFormErrors } from '@/lib/formError';
import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { kidSchema, type KidFormValues } from './kidSchema';
import { useCreateKid, useUpdateKid } from '@/lib/mutations';
import { useKid } from '@/lib/queries';
import { ApiError } from '@/lib/api';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { InterestsField } from './InterestsField';
import { AlertOnField } from './AlertOnField';
import { SchoolHolidaysField } from './SchoolHolidaysField';
import { SchoolYearRangesField } from './SchoolYearRangesField';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { KidDetail } from '@/lib/types';

interface KidFormProps {
  mode: 'create' | 'edit';
  id?: number;
}

function kidToFormValues(k: KidDetail): KidFormValues {
  return {
    name: k.name,
    dob: k.dob,
    interests: k.interests,
    school_weekdays: k.school_weekdays as KidFormValues['school_weekdays'],
    school_time_start: k.school_time_start,
    school_time_end: k.school_time_end,
    school_year_ranges: k.school_year_ranges,
    school_holidays: k.school_holidays,
    max_distance_mi: k.max_distance_mi,
    max_drive_minutes: k.max_drive_minutes,
    alert_score_threshold: k.alert_score_threshold,
    alert_on: k.alert_on,
    notes: k.notes,
    active: k.active,
  };
}

const DEFAULT_CREATE_VALUES: KidFormValues = {
  name: '',
  dob: '',
  interests: [],
  school_weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'] as KidFormValues['school_weekdays'],
  school_time_start: null,
  school_time_end: null,
  school_year_ranges: [],
  school_holidays: [],
  max_distance_mi: null,
  max_drive_minutes: null,
  alert_score_threshold: 0.6,
  alert_on: {},
  notes: null,
  active: true,
};

export function KidForm({ mode, id }: KidFormProps) {
  const navigate = useNavigate();
  const create = useCreateKid();
  const update = useUpdateKid();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  // useKid called unconditionally (Rules of Hooks); `enabled` gates the network call.
  // For create mode, we pass id=0 + enabled=false so it never runs.
  const kidQuery = useKid(mode === 'edit' && id ? id : 0);

  // Create form hook before checking loading state to satisfy Rules of Hooks
  const form = useForm({
    defaultValues:
      mode === 'edit' && kidQuery.data ? kidToFormValues(kidQuery.data) : DEFAULT_CREATE_VALUES,
    validators: {
      onChange: kidSchema,
    },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        if (mode === 'create') {
          const created = await create.mutateAsync(value);
          navigate({ to: '/kids/$id/matches', params: { id: String(created.id) } });
        } else if (id) {
          await update.mutateAsync({ id, patch: value });
          navigate({ to: '/kids/$id/matches', params: { id: String(id) } });
        }
      } catch (err) {
        if (err instanceof ApiError && typeof err.body === 'object' && err.body !== null) {
          const detail = (err.body as Record<string, unknown>).detail;
          setErrorMsg(String(detail ?? 'Failed to save'));
        } else {
          setErrorMsg((err as Error).message ?? 'Failed to save');
        }
      }
    },
  });

  // Edit mode + data still loading → render Skeleton until kid data arrives.
  if (mode === 'edit' && (kidQuery.isLoading || !kidQuery.data)) {
    return <Skeleton className="h-96 w-full max-w-2xl" />;
  }

  const inFlight = create.isPending || update.isPending;

  const handleCancel = () => {
    if (form.state.isDirty) {
      setShowCancelConfirm(true);
    } else {
      navigateBack();
    }
  };

  const navigateBack = () => {
    if (mode === 'edit' && id) {
      navigate({ to: '/kids/$id/matches', params: { id: String(id) } });
    } else {
      navigate({ to: '/' });
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        form.handleSubmit();
      }}
      className="max-w-2xl space-y-6"
    >
      {errorMsg && <ErrorBanner message={errorMsg} />}

      <form.Field
        name="name"
        children={(field) => (
          <div>
            <label htmlFor="name" className="block text-sm font-medium">
              Name
            </label>
            <input
              id="name"
              autoFocus={mode === 'create'}
              type="text"
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              aria-invalid={field.state.meta.errors.length > 0}
              className="mt-1 block w-full rounded border border-input px-3 py-2"
            />
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <form.Field
        name="dob"
        children={(field) => (
          <div>
            <label htmlFor="dob" className="block text-sm font-medium">
              Date of Birth
            </label>
            <input
              id="dob"
              type="date"
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              aria-invalid={field.state.meta.errors.length > 0}
              className="mt-1 block w-full rounded border border-input px-3 py-2"
            />
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <form.Field
        name="interests"
        children={(field) => (
          <InterestsField
            value={field.state.value}
            onChange={field.handleChange}
            error={field.state.meta.errors[0] ? String(field.state.meta.errors[0]) : undefined}
          />
        )}
      />

      <form.Field
        name="school_weekdays"
        children={(field) => (
          <div>
            <label className="block text-sm font-medium">School Weekdays</label>
            <div className="mt-2 grid grid-cols-4 gap-2">
              {(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const).map((day) => (
                <label key={day} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={field.state.value.includes(day)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        field.handleChange([...field.state.value, day]);
                      } else {
                        field.handleChange(field.state.value.filter((d) => d !== day));
                      }
                    }}
                    className="rounded"
                  />
                  <span className="text-xs capitalize">{day}</span>
                </label>
              ))}
            </div>
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <div className="grid grid-cols-2 gap-4">
        <form.Field
          name="school_time_start"
          children={(field) => (
            <div>
              <label htmlFor="school_time_start" className="block text-sm font-medium">
                School Start Time
              </label>
              <input
                id="school_time_start"
                type="time"
                value={field.state.value ?? ''}
                onChange={(e) => field.handleChange(e.target.value || null)}
                onBlur={field.handleBlur}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              />
            </div>
          )}
        />
        <form.Field
          name="school_time_end"
          children={(field) => (
            <div>
              <label htmlFor="school_time_end" className="block text-sm font-medium">
                School End Time
              </label>
              <input
                id="school_time_end"
                type="time"
                value={field.state.value ?? ''}
                onChange={(e) => field.handleChange(e.target.value || null)}
                onBlur={field.handleBlur}
                aria-invalid={field.state.meta.errors.length > 0}
                className="mt-1 block w-full rounded border border-input px-3 py-2"
              />
              {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
                <p key={i} className="mt-1 text-xs text-destructive">
                  {m}
                </p>
              ))}
            </div>
          )}
        />
      </div>

      <form.Field
        name="school_year_ranges"
        children={(field) => (
          <SchoolYearRangesField value={field.state.value} onChange={field.handleChange} />
        )}
      />

      <form.Field
        name="school_holidays"
        children={(field) => (
          <SchoolHolidaysField value={field.state.value} onChange={field.handleChange} />
        )}
      />

      <form.Field
        name="max_distance_mi"
        children={(field) => (
          <div>
            <label htmlFor="max_distance_mi" className="block text-sm font-medium">
              Max Distance (miles)
            </label>
            <div className="mt-2 flex items-center gap-3">
              <input
                id="max_distance_mi"
                type="number"
                min="1"
                max="50"
                step="0.5"
                disabled={field.state.value === null}
                value={field.state.value ?? ''}
                onChange={(e) => {
                  const val = e.target.value ? parseFloat(e.target.value) : null;
                  field.handleChange(val);
                }}
                className="block flex-1 rounded border border-input px-3 py-2 disabled:opacity-50"
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={field.state.value === null}
                  onChange={(e) => {
                    field.handleChange(e.target.checked ? null : 5);
                  }}
                />
                No limit
              </label>
            </div>
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <form.Field
        name="max_drive_minutes"
        children={(field) => (
          <div>
            <label htmlFor="max_drive_minutes" className="block text-sm font-medium">
              Max Drive Time (minutes)
            </label>
            <p className="mt-1 text-xs text-muted-foreground">
              Routed driving minutes via OSRM. Takes precedence over Max Distance when set, but only
              if <code>YAS_DRIVE_TIME_ENABLED=true</code> on the server.
            </p>
            <div className="mt-2 flex items-center gap-3">
              <input
                id="max_drive_minutes"
                type="number"
                min="1"
                max="180"
                step="1"
                disabled={field.state.value === null}
                value={field.state.value ?? ''}
                onChange={(e) => {
                  const val = e.target.value ? parseInt(e.target.value, 10) : null;
                  field.handleChange(val);
                }}
                className="block flex-1 rounded border border-input px-3 py-2 disabled:opacity-50"
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={field.state.value === null}
                  onChange={(e) => {
                    field.handleChange(e.target.checked ? null : 30);
                  }}
                />
                Use distance instead
              </label>
            </div>
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <form.Field
        name="alert_score_threshold"
        children={(field) => (
          <div>
            <div className="flex items-center justify-between">
              <label htmlFor="alert_score_threshold" className="text-sm font-medium">
                Alert Score Threshold
              </label>
              <span className="text-xs text-muted-foreground">{field.state.value.toFixed(2)}</span>
            </div>
            <input
              id="alert_score_threshold"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={field.state.value}
              onChange={(e) => field.handleChange(parseFloat(e.target.value))}
              className="mt-2 w-full"
            />
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      <form.Field
        name="alert_on"
        children={(field) => (
          <AlertOnField value={field.state.value} onChange={field.handleChange} />
        )}
      />

      <form.Field
        name="notes"
        children={(field) => (
          <div>
            <label htmlFor="notes" className="block text-sm font-medium">
              Notes
            </label>
            <textarea
              id="notes"
              value={field.state.value ?? ''}
              onChange={(e) => field.handleChange(e.target.value || null)}
              onBlur={field.handleBlur}
              maxLength={2000}
              rows={4}
              className="mt-1 block w-full rounded border border-input px-3 py-2"
            />
            {uniqueFormErrors(field.state.meta.errors).map((m, i) => (
              <p key={i} className="mt-1 text-xs text-destructive">
                {m}
              </p>
            ))}
          </div>
        )}
      />

      {mode === 'edit' && (
        <form.Field
          name="active"
          children={(field) => (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={field.state.value}
                onChange={(e) => field.handleChange(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm font-medium">Active</span>
            </label>
          )}
        />
      )}

      <div className="flex gap-2 pt-4">
        <Button type="submit" disabled={inFlight || !form.state.canSubmit}>
          {inFlight ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="outline" onClick={handleCancel} disabled={inFlight}>
          Cancel
        </Button>
      </div>

      <ConfirmDialog
        open={showCancelConfirm}
        onOpenChange={setShowCancelConfirm}
        title="Discard changes?"
        description="Your edits will be lost."
        confirmLabel="Discard"
        destructive
        onConfirm={() => {
          setShowCancelConfirm(false);
          navigateBack();
        }}
      />
    </form>
  );
}
