import { createFileRoute } from '@tanstack/react-router';
import { OfferingsBrowserPage } from '@/components/offerings/OfferingsBrowserPage';

export const Route = createFileRoute('/offerings')({
  component: OfferingsBrowserPage,
});
