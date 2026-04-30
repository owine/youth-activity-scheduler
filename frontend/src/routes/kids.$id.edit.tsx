import { createFileRoute } from '@tanstack/react-router';
import { KidForm } from '@/components/kids/KidForm';

export const Route = createFileRoute('/kids/$id/edit')({ component: EditKidPage });

function EditKidPage() {
  const { id } = Route.useParams();
  return (
    <div className="p-4">
      <h1 className="text-xl font-semibold mb-4">Edit kid</h1>
      <KidForm mode="edit" id={Number(id)} />
    </div>
  );
}
