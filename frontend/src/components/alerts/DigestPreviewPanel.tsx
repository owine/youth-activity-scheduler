import { Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { useDigestPreview, useKids } from '@/lib/queries';

interface Props {
  searchParams: Record<string, string | undefined>;
  onKidChange: (kidId: number) => void;
}

export function DigestPreviewPanel({ searchParams, onKidChange }: Props) {
  const kids = useKids();

  const selectedKidId = searchParams.kid_digest
    ? Number(searchParams.kid_digest)
    : (kids.data?.[0]?.id ?? null);

  const preview = useDigestPreview(selectedKidId);

  if (kids.isLoading) return <Skeleton className="h-64 w-full" />;
  if (kids.isError)
    return <ErrorBanner message="Failed to load kids" onRetry={() => kids.refetch()} />;

  if (!kids.data || kids.data.length === 0) {
    return (
      <EmptyState>
        Add a kid first to preview a digest.{' '}
        <Link to="/kids/new" className="underline">
          Add kid
        </Link>
        .
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label
          htmlFor="digest-kid"
          className="block text-xs font-medium uppercase text-muted-foreground"
        >
          Kid
        </label>
        <select
          id="digest-kid"
          value={selectedKidId ?? ''}
          onChange={(e) => onKidChange(Number(e.target.value))}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          {kids.data.map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </select>
      </div>
      {preview.isLoading && <Skeleton className="h-[600px] w-full" />}
      {preview.isError && (
        <ErrorBanner message="Failed to load digest preview" onRetry={() => preview.refetch()} />
      )}
      {preview.data && (
        <>
          <div className="rounded bg-muted p-3 text-sm">
            <span className="font-medium">Subject:</span> {preview.data.subject}
          </div>
          <iframe
            srcDoc={preview.data.body_html}
            sandbox="allow-same-origin"
            className="w-full h-[600px] rounded border border-border"
            title="Digest preview"
          />
          <p className="text-xs italic text-muted-foreground">
            This is a preview of the next scheduled digest based on the last 24 hours of activity.
          </p>
        </>
      )}
    </div>
  );
}
