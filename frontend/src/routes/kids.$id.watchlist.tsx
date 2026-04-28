import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/kids/$id/watchlist')({
  component: KidWatchlistPage,
});

function KidWatchlistPage() {
  const { id } = Route.useParams();
  return <h2 className="text-2xl">Kid {id} — Watchlist</h2>;
}
