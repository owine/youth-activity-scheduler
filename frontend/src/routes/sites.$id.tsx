import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/sites/$id')({
  component: SiteDetailPage,
});

function SiteDetailPage() {
  const { id } = Route.useParams();
  return <h2 className="text-2xl">Site {id}</h2>;
}
