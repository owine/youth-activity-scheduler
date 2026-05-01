import { createFileRoute } from '@tanstack/react-router';
import { SiteWizard } from '@/components/sites/SiteWizard';

export const Route = createFileRoute('/sites/new')({ component: NewSitePage });

function NewSitePage() {
  return (
    <div className="p-4">
      <h1 className="mb-4 text-xl font-semibold">Add site</h1>
      <SiteWizard />
    </div>
  );
}
