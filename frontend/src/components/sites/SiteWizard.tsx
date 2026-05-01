import { useState } from 'react';
import { useForm } from '@tanstack/react-form';
import { useNavigate } from '@tanstack/react-router';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ApiError } from '@/lib/api';
import { useCreateSite, useDiscoverPages, useAddPage, useCrawlNow } from '@/lib/mutations';
import type { Candidate, PageKind } from '@/lib/types';
import { CandidateList } from './CandidateList';
import { ManualPageEntry, type ManualEntry } from './ManualPageEntry';

const formSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(120),
  base_url: z.string().url('Must be a valid URL'),
});

export function SiteWizard() {
  const navigate = useNavigate();
  const createSite = useCreateSite();
  const discover = useDiscoverPages();
  const addPage = useAddPage();
  const crawlNow = useCrawlNow();

  const [siteId, setSiteId] = useState<number | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const [manualEntries, setManualEntries] = useState<ManualEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);

  const form = useForm({
    defaultValues: { name: '', base_url: '' } as { name: string; base_url: string },
    validators: { onChange: formSchema, onMount: formSchema },
    onSubmit: async () => {}, // submit happens via explicit button below
  });

  const inDiscover = createSite.isPending || discover.isPending;
  const inSave = addPage.isPending;

  const handleDiscover = async () => {
    setErrorMsg(null);
    const values = form.state.values;
    try {
      let id = siteId;
      if (id === null) {
        const created = await createSite.mutateAsync({
          name: values.name,
          base_url: values.base_url,
        });
        id = created.id;
        setSiteId(id);
      }
      const result = await discover.mutateAsync({ siteId: id });
      setCandidates(result.candidates);
      // Pre-check html candidates with score >= 0.7
      setSelectedUrls(
        new Set(
          result.candidates.filter((c) => c.kind === 'html' && c.score >= 0.7).map((c) => c.url),
        ),
      );
    } catch (err) {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      const msg = detail ?? (err as Error).message;
      setErrorMsg(msg ? `Discovery failed: ${msg}` : 'Discovery failed');
    }
  };

  const handleEditUrl = () => {
    setSiteId(null);
    setCandidates([]);
    setSelectedUrls(new Set());
    setManualEntries([]);
    setErrorMsg(null);
  };

  const pagesPending = (): { url: string; kind: PageKind }[] => {
    const fromCandidates = candidates
      .filter((c) => c.kind === 'html' && selectedUrls.has(c.url))
      .map((c) => ({ url: c.url, kind: 'schedule' as PageKind }));
    return [...fromCandidates, ...manualEntries];
  };

  const handleSave = async () => {
    if (siteId === null) return;
    const pending = pagesPending();
    setErrorMsg(null);
    setTotalCount(pending.length);
    setSavedCount(0);
    let saved = 0;
    for (const p of pending) {
      try {
        await addPage.mutateAsync({ siteId, url: p.url, kind: p.kind });
        saved++;
        setSavedCount(saved);
        // Remove the just-saved URL from state so retries skip it.
        setSelectedUrls((prev) => {
          const next = new Set(prev);
          next.delete(p.url);
          return next;
        });
        setManualEntries((prev) => prev.filter((e) => e.url !== p.url));
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(
          `Added ${saved} of ${pending.length} pages — ${detail ?? (err as Error).message}`,
        );
        return;
      }
    }
    // Soft-fire crawl-now; don't block navigate on failure.
    try {
      await crawlNow.mutateAsync({ siteId });
    } catch {
      // intentionally swallowed — wizard's primary work succeeded.
    }
    navigate({ to: '/sites/$id', params: { id: String(siteId) } });
  };

  const handleCancel = () => {
    if (siteId === null && form.state.isDirty) {
      setShowCancelConfirm(true);
    } else {
      navigate({ to: '/sites' });
    }
  };

  const candidateUrls = new Set(candidates.filter((c) => c.kind === 'html').map((c) => c.url));
  const totalPagesPending = pagesPending().length;
  const discovered = siteId !== null && !inDiscover;

  return (
    <div className="max-w-2xl space-y-4">
      {errorMsg && <ErrorBanner message={errorMsg} />}

      <form.Field
        name="name"
        children={(field) => (
          <div>
            <label htmlFor="name" className="block text-sm font-medium">
              Name
            </label>
            <input
              id="name"
              type="text"
              readOnly={siteId !== null}
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              className="w-full rounded border border-border bg-background px-2 py-1"
            />
          </div>
        )}
      />
      <form.Field
        name="base_url"
        children={(field) => (
          <div>
            <label htmlFor="base_url" className="block text-sm font-medium">
              Base URL
            </label>
            <input
              id="base_url"
              type="text"
              readOnly={siteId !== null}
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              className="w-full rounded border border-border bg-background px-2 py-1"
            />
          </div>
        )}
      />

      {!discovered ? (
        <form.Subscribe
          selector={(state) => state.canSubmit}
          children={(canSubmit) => (
            <Button type="button" onClick={handleDiscover} disabled={inDiscover || !canSubmit}>
              {inDiscover
                ? 'Asking Claude to find schedule pages — this can take up to 30 seconds…'
                : 'Discover pages'}
            </Button>
          )}
        />
      ) : (
        <Button type="button" variant="outline" onClick={handleEditUrl}>
          Edit URL & re-discover
        </Button>
      )}

      {discovered && (
        <>
          <CandidateList
            candidates={candidates}
            selectedUrls={selectedUrls}
            onChange={setSelectedUrls}
          />
          <ManualPageEntry
            existingUrls={candidateUrls}
            value={manualEntries}
            onChange={setManualEntries}
          />
          <div className="flex gap-2">
            <Button type="button" onClick={handleSave} disabled={inSave || totalPagesPending === 0}>
              {inSave ? `Adding ${savedCount + 1} of ${totalCount}…` : 'Create site'}
            </Button>
            <Button type="button" variant="outline" onClick={handleCancel} disabled={inSave}>
              Cancel
            </Button>
          </div>
        </>
      )}

      {!discovered && (
        <Button type="button" variant="outline" onClick={handleCancel} disabled={inDiscover}>
          Cancel
        </Button>
      )}

      <ConfirmDialog
        open={showCancelConfirm}
        onOpenChange={setShowCancelConfirm}
        title="Discard changes?"
        description="Your inputs will be lost."
        confirmLabel="Discard"
        destructive
        onConfirm={() => {
          setShowCancelConfirm(false);
          navigate({ to: '/sites' });
        }}
      />
    </div>
  );
}
