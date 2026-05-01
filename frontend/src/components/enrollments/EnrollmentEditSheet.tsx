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
});

interface Props {
  enrollment: Enrollment | null;
  kidId: number;
  onClose: () => void;
}

export function EnrollmentEditSheet({ enrollment, kidId, onClose }: Props) {
  const update = useUpdateEnrollment();

  const form = useForm({
    defaultValues: {
      notes: enrollment?.notes ?? null,
      // Slice ISO datetime to YYYY-MM-DD for <input type="date">.
      enrolled_at: enrollment?.enrolled_at ? enrollment.enrolled_at.slice(0, 10) : null,
    },
    validators: { onChange: schema },
    onSubmit: async ({ value }) => {
      if (!enrollment) return;
      const enrolled_at = value.enrolled_at ? `${value.enrolled_at}T00:00:00Z` : null;
      await update.mutateAsync({
        enrollmentId: enrollment.id,
        kidId,
        patch: { notes: value.notes, enrolled_at },
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
            Edit notes and enrolled-at date for {enrollment.offering.name}.
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
