import { createFileRoute } from '@tanstack/react-router';
import { EnrollmentsList } from '@/components/enrollments/EnrollmentsList';

export const Route = createFileRoute('/kids/$id/enrollments')({ component: EnrollmentsPage });

function EnrollmentsPage() {
  const { id } = Route.useParams();
  return <EnrollmentsList kidId={Number(id)} />;
}
