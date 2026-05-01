import { Link } from '@tanstack/react-router';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { OfferingScheduleLine } from '@/components/common/OfferingScheduleLine';
import { useUpdateEnrollment } from '@/lib/mutations';
import { relDate } from '@/lib/format';
import type { Enrollment, EnrollmentStatus } from '@/lib/types';

const STATUSES: EnrollmentStatus[] = [
  'interested',
  'enrolled',
  'waitlisted',
  'completed',
  'cancelled',
];

interface Props {
  enrollment: Enrollment;
  kidId: number;
  isPending: boolean;
  onEdit: (enrollment: Enrollment) => void;
}

export function EnrollmentRow({ enrollment, kidId, isPending, onEdit }: Props) {
  const update = useUpdateEnrollment();

  const handleStatusChange = (next: EnrollmentStatus) => {
    update.mutate({ enrollmentId: enrollment.id, kidId, patch: { status: next } });
  };

  return (
    <Card className="p-3 space-y-1">
      <div className="flex items-center gap-2">
        <div className="flex-1 font-semibold">{enrollment.offering.name}</div>
        <select
          aria-label={`Status for ${enrollment.offering.name}`}
          value={enrollment.status}
          disabled={isPending}
          onChange={(e) => handleStatusChange(e.target.value as EnrollmentStatus)}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {enrollment.status === 'enrolled' && (
          <Link
            to="/kids/$id/calendar"
            params={{ id: String(kidId) }}
            aria-label="View block on calendar"
            className="rounded bg-orange-100 px-2 py-1 text-xs text-orange-900 dark:bg-orange-900/30 dark:text-orange-200"
          >
            🚫 Blocks calendar
          </Link>
        )}
      </div>
      <OfferingScheduleLine offering={enrollment.offering} />
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {enrollment.enrolled_at && <span>Enrolled {relDate(enrollment.enrolled_at)}</span>}
        {enrollment.enrolled_at && enrollment.notes && <span>·</span>}
        {enrollment.notes && <span className="italic">"{enrollment.notes}"</span>}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => onEdit(enrollment)}
        >
          Edit
        </Button>
      </div>
    </Card>
  );
}
