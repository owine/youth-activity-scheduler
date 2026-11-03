import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { useUpdateEnrollment } from '@/lib/mutations';
import type { Enrollment } from '@/lib/types';

const schema = z.object({
  notes: z.string().max(500).nullable(),
  enrolled_at: z.string().nullable(), // 'YYYY-MM-DD' or null
  days_of_week: z.array(z.string()),
});

const DAY_LABELS: Record<string, string> = {
  mon: 'Mon',
  tue: 'Tue',
  wed: 'Wed',
  thu: 'Thu',
  fri: 'Fri',
  sat: 'Sat',
  sun: 'Sun',
};

interface Props {
  enrollment: Enrollment | null;
  kidId: number;
  onClose: () => void;
}

export function EnrollmentEditSheet({ enrollment, kidId, onClose }: Props) {
  const update = useUpdateEnrollment();
  // A pick-one-day program ("choose a day of the week") lists several days but
  // the kid attends only the chosen one(s), which drive the calendar and the
  // unavailability block (#636). The picker also shows when the enrollment
  // already has a choice, even if a re-extraction cleared attends_one_day: the
  // backend keeps using a stored choice, so the user must be able to see and
  // clear it.
  const storedDays = enrollment?.days_of_week ?? [];
  const pickDays =
    enrollment !== null &&
    (enrollment.offering.attends_one_day || storedDays.length > 0) &&
    enrollment.offering.days_of_week.length > 1;

  const form = useForm({
    defaultValues: {
      notes: enrollment?.notes ?? null,
      // Slice ISO datetime to YYYY-MM-DD for <input type="date">.
      enrolled_at: enrollment?.enrolled_at ? enrollment.enrolled_at.slice(0, 10) : null,
      // Only days the offering still lists: a stale chosen day would have no
      // checkbox to untick, and every save would be rejected with a 422. An
      // empty result saves as "no choice".
      days_of_week: storedDays.filter((d) => enrollment?.offering.days_of_week.includes(d)),
    },
    validators: { onChange: schema },
    onSubmit: async ({ value }) => {
      if (!enrollment) return;
      const enrolled_at = value.enrolled_at ? `${value.enrolled_at}T00:00:00Z` : null;
      await update.mutateAsync({
        enrollmentId: enrollment.id,
        kidId,
        patch: {
          notes: value.notes,
          enrolled_at,
          ...(pickDays
            ? { days_of_week: value.days_of_week.length ? value.days_of_week : null }
            : {}),
        },
      });
      onClose();
    },
  });

  if (!enrollment) return null; // unmount when closed

  return (
    <Sheet open={enrollment !== null} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <SheetContent className="w-full sm:max-w-md flex flex-col">
        <SheetHeader>
          <SheetTitle>Edit enrollment</SheetTitle>
          <SheetDescription>
            Edit {pickDays ? 'the day attended, ' : ''}notes and enrolled-at date for{' '}
            {enrollment.offering.name}.
          </SheetDescription>
        </SheetHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            form.handleSubmit();
          }}
          className="mt-4 space-y-4 flex-1"
        >
          <form.Field
            name="notes"
            children={(field) => (
              <div>
                <label htmlFor="notes" className="block text-sm font-medium">
                  Notes
                </label>
                <textarea
                  id="notes"
                  rows={4}
                  value={field.state.value ?? ''}
                  onChange={(e) => field.handleChange(e.target.value || null)}
                  className="w-full rounded border border-border bg-background px-2 py-1"
                />
              </div>
            )}
          />
          <form.Field
            name="enrolled_at"
            children={(field) => (
              <div>
                <label htmlFor="enrolled_at" className="block text-sm font-medium">
                  Enrolled at
                </label>
                <input
                  id="enrolled_at"
                  type="date"
                  value={field.state.value ?? ''}
                  onChange={(e) => field.handleChange(e.target.value || null)}
                  className="w-full rounded border border-border bg-background px-2 py-1"
                />
              </div>
            )}
          />
          {pickDays && (
            <form.Field
              name="days_of_week"
              children={(field) => (
                <fieldset>
                  <legend className="block text-sm font-medium">Which day(s)?</legend>
                  <p className="text-xs text-muted-foreground">
                    This program lets you pick a day. Leave all unchecked if you haven&apos;t chosen
                    yet; until then every listed day counts as busy.
                  </p>
                  <div className="mt-1 flex flex-wrap gap-3">
                    {enrollment.offering.days_of_week.map((day) => (
                      <label key={day} className="flex items-center gap-1 text-sm">
                        <input
                          type="checkbox"
                          checked={field.state.value.includes(day)}
                          onChange={(e) =>
                            field.handleChange(
                              e.target.checked
                                ? enrollment.offering.days_of_week.filter(
                                    (d) => d === day || field.state.value.includes(d),
                                  )
                                : field.state.value.filter((d) => d !== day),
                            )
                          }
                        />
                        {DAY_LABELS[day] ?? day}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
            />
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
