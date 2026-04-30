import { createFileRoute } from '@tanstack/react-router';
import { KidForm } from '@/components/kids/KidForm';

export const Route = createFileRoute('/kids/new')({ component: NewKidPage });

function NewKidPage() {
  return (
    <div className="p-4">
      <h1 className="text-xl font-semibold mb-4">Add kid</h1>
      <KidForm mode="create" />
    </div>
  );
}
