import { useForm } from '@tanstack/react-form';
import { useState } from 'react';
import { z } from 'zod';
import { useCreateWatchlistEntry, useUpdateWatchlistEntry } from '@/lib/mutations';
import { ApiError } from '@/lib/api';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import type { WatchlistEntry } from '@/lib/types';

const watchlistSchema = z.object({
  pattern: z.string().trim().min(1, 'Pattern is required').max(200),
  priority: z.enum(['low', 'normal', 'high']),
  site_id: z.number().int().nullable(),
  ignore_hard_gates: z.boolean(),
  notes: z.string().max(500).nullable(),
  active: z.boolean(),
});

type WatchlistFormValues = z.infer<typeof watchlistSchema>;

const DEFAULT_CREATE_VALUES: WatchlistFormValues = {
  pattern: '',
  priority: 'normal',
  site_id: null,
  ignore_hard_gates: false,
  notes: null,
  active: true,
};

function entryToFormValues(entry: WatchlistEntry): WatchlistFormValues {
  return {
    pattern: entry.pattern,
    priority: entry.priority as WatchlistFormValues['priority'],
    site_id: entry.site_id,
    ignore_hard_gates: entry.ignore_hard_gates,
    notes: entry.notes,
    active: entry.active,
  };
}

interface WatchlistEntrySheetProps {
  kidId: number;
  mode: 'create' | 'edit';
  entry?: WatchlistEntry;
  open: boolean;
  onClose: () => void;
}

export function WatchlistEntrySheet({
  kidId,
  mode,
  entry,
  open,
  onClose,
}: WatchlistEntrySheetProps) {
  const create = useCreateWatchlistEntry();
  const update = useUpdateWatchlistEntry();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const form = useForm({
    defaultValues: mode === 'edit' && entry ? entryToFormValues(entry) : DEFAULT_CREATE_VALUES,
    validators: {
      onChange: watchlistSchema,
    },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        if (mode === 'create') {
          await create.mutateAsync({
            kidId,
            ...value,
          });
          onClose();
        } else if (entry) {
          await update.mutateAsync({
            kidId,
            entryId: entry.id,
            patch: value,
          });
          onClose();
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

  const handleCancel = () => {
    if (form.state.isDirty) {
      setShowCancelConfirm(true);
    } else {
      onClose();
    }
  };

  const inFlight = create.isPending || update.isPending;

  return (
    <>
      <Sheet open={open} onOpenChange={(isOpen) => !isOpen && handleCancel()}>
        <SheetContent className="w-full sm:max-w-md flex flex-col">
          <SheetHeader>
            <SheetTitle>
              {mode === 'create' ? 'Add Watchlist Entry' : 'Edit Watchlist Entry'}
            </SheetTitle>
            <SheetDescription>
              {mode === 'create'
                ? 'Create a new watchlist entry to track activity patterns.'
                : 'Update this watchlist entry.'}
            </SheetDescription>
          </SheetHeader>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              form.handleSubmit();
            }}
            className="flex-1 space-y-6 overflow-y-auto py-4"
          >
            {errorMsg && <ErrorBanner message={errorMsg} />}

            <form.Field
              name="pattern"
              children={(field) => (
                <div>
                  <label htmlFor="pattern" className="block text-sm font-medium">
                    Pattern
                  </label>
                  <input
                    id="pattern"
                    autoFocus={mode === 'create'}
                    type="text"
                    placeholder="e.g., soccer camp"
                    value={field.state.value}
                    onChange={(e) => field.handleChange(e.target.value)}
                    onBlur={field.handleBlur}
                    aria-invalid={field.state.meta.errors.length > 0}
                    className="mt-1 block w-full rounded border border-input px-3 py-2"
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
              name="priority"
              children={(field) => (
                <div>
                  <label htmlFor="priority" className="block text-sm font-medium">
                    Priority
                  </label>
                  <select
                    id="priority"
                    value={field.state.value}
                    onChange={(e) =>
                      field.handleChange(e.target.value as 'low' | 'normal' | 'high')
                    }
                    onBlur={field.handleBlur}
                    className="mt-1 block w-full rounded border border-input px-3 py-2"
                  >
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                  </select>
                </div>
              )}
            />

            <form.Field
              name="site_id"
              children={(field) => (
                <div>
                  <label htmlFor="site_id" className="block text-sm font-medium">
                    Site (optional)
                  </label>
                  <input
                    id="site_id"
                    type="number"
                    placeholder="Leave blank for any site"
                    value={field.state.value ?? ''}
                    onChange={(e) =>
                      field.handleChange(e.target.value === '' ? null : Number(e.target.value))
                    }
                    onBlur={field.handleBlur}
                    className="mt-1 block w-full rounded border border-input px-3 py-2"
                  />
                </div>
              )}
            />

            <form.Field
              name="notes"
              children={(field) => (
                <div>
                  <label htmlFor="notes" className="block text-sm font-medium">
                    Notes (optional)
                  </label>
                  <textarea
                    id="notes"
                    placeholder="Add any notes about this pattern"
                    value={field.state.value ?? ''}
                    onChange={(e) => field.handleChange(e.target.value || null)}
                    onBlur={field.handleBlur}
                    rows={3}
                    className="mt-1 block w-full rounded border border-input px-3 py-2"
                  />
                </div>
              )}
            />

            <form.Field
              name="ignore_hard_gates"
              children={(field) => (
                <div>
                  <label className="flex items-center gap-2">
                    <input
                      id="ignore_hard_gates"
                      type="checkbox"
                      checked={field.state.value}
                      onChange={(e) => field.handleChange(e.target.checked)}
                      onBlur={field.handleBlur}
                      className="h-4 w-4 rounded border border-input"
                    />
                    <span className="text-sm font-medium">Ignore hard gates</span>
                  </label>
                </div>
              )}
            />

            <form.Field
              name="active"
              children={(field) => (
                <div>
                  <label className="flex items-center gap-2">
                    <input
                      id="active"
                      type="checkbox"
                      checked={field.state.value}
                      onChange={(e) => field.handleChange(e.target.checked)}
                      onBlur={field.handleBlur}
                      className="h-4 w-4 rounded border border-input"
                    />
                    <span className="text-sm font-medium">Active</span>
                  </label>
                </div>
              )}
            />

            <div className="flex justify-end gap-2 border-t pt-4">
              <Button type="button" variant="outline" onClick={handleCancel} disabled={inFlight}>
                Cancel
              </Button>
              <Button type="submit" disabled={inFlight}>
                {inFlight ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </form>
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={showCancelConfirm}
        onOpenChange={setShowCancelConfirm}
        title="Discard changes?"
        description="You have unsaved changes. Are you sure you want to discard them?"
        confirmLabel="Discard"
        destructive
        onConfirm={() => {
          setShowCancelConfirm(false);
          onClose();
        }}
      />
    </>
  );
}
