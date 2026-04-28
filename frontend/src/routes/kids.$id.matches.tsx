import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/kids/$id/matches')({
  component: KidMatchesPage,
});

function KidMatchesPage() {
  const { id } = Route.useParams();
  return <h2 className="text-2xl">Kid {id} — Matches</h2>;
}
