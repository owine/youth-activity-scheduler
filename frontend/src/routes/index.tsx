import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/')({
  component: InboxPage,
});

function InboxPage() {
  return <h2 className="text-2xl">Inbox</h2>;
}
