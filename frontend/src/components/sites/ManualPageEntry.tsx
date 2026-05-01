import { useState } from 'react';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import type { PageKind } from '@/lib/types';

export interface ManualEntry {
  url: string;
  kind: PageKind;
}

interface Props {
  existingUrls: Set<string>;
  value: ManualEntry[];
  onChange: (next: ManualEntry[]) => void;
}

const KINDS: PageKind[] = ['schedule', 'registration', 'list', 'other'];
const urlSchema = z.string().url('Must be a valid URL');

export function ManualPageEntry({ existingUrls, value, onChange }: Props) {
  const [draftUrl, setDraftUrl] = useState('');
  const [draftKind, setDraftKind] = useState<PageKind>('schedule');
  const [error, setError] = useState<string | null>(null);

  const handleAdd = () => {
    setError(null);
    const trimmed = draftUrl.trim();
    const parsed = urlSchema.safeParse(trimmed);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? 'Invalid URL');
      return;
    }
    if (existingUrls.has(trimmed) || value.some((e) => e.url === trimmed)) {
      setError('URL already in list');
      return;
    }
    onChange([...value, { url: trimmed, kind: draftKind }]);
    setDraftUrl('');
    setDraftKind('schedule');
  };

  const handleRemove = (url: string) => {
    onChange(value.filter((e) => e.url !== url));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor="manual-url" className="block text-sm font-medium">
            Add a URL manually
          </label>
          <input
            id="manual-url"
            type="text"
            aria-label="manual url"
            value={draftUrl}
            onChange={(e) => setDraftUrl(e.target.value)}
            placeholder="https://example.com/schedule"
            className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label htmlFor="manual-kind" className="block text-sm font-medium">
            Kind
          </label>
          <select
            id="manual-kind"
            aria-label="manual kind"
            value={draftKind}
            onChange={(e) => setDraftKind(e.target.value as PageKind)}
            className="rounded border border-border bg-background px-2 py-1 text-sm"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <Button type="button" onClick={handleAdd}>
          Add
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      {value.length > 0 && (
        <ul className="space-y-1">
          {value.map((e) => (
            <li
              key={e.url}
              className="flex items-center justify-between rounded bg-accent px-2 py-1 text-xs"
            >
              <span>
                {e.url} <span className="text-muted-foreground">({e.kind})</span>
              </span>
              <button
                type="button"
                aria-label={`Remove ${e.url}`}
                onClick={() => handleRemove(e.url)}
                className="ml-2"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
