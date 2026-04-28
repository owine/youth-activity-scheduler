import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/sites/')({
  component: SitesPage,
});

function SitesPage() {
  return <h2 className="text-2xl">Sites</h2>;
}
