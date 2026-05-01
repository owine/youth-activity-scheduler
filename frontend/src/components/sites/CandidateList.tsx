import { useState } from 'react';
import type { Candidate } from '@/lib/types';

interface Props {
  candidates: Candidate[];
  selectedUrls: Set<string>;
  onChange: (next: Set<string>) => void;
}

const HIGH_CONFIDENCE_THRESHOLD = 0.7;

export function CandidateList({ candidates, selectedUrls, onChange }: Props) {
  const [expanded, setExpanded] = useState(false);

  const html = candidates.filter((c) => c.kind === 'html');
  const sorted = [...html].sort((a, b) => b.score - a.score);
  const high = sorted.filter((c) => c.score >= HIGH_CONFIDENCE_THRESHOLD);
  const low = sorted.filter((c) => c.score < HIGH_CONFIDENCE_THRESHOLD);

  const toggle = (url: string) => {
    const next = new Set(selectedUrls);
    if (next.has(url)) next.delete(url);
    else next.add(url);
    onChange(next);
  };

  const renderRow = (c: Candidate, showReason: boolean) => (
    <li key={c.url} className="flex items-start gap-2 rounded border border-border p-2">
      <input
        type="checkbox"
        id={`cand-${c.url}`}
        checked={selectedUrls.has(c.url)}
        onChange={() => toggle(c.url)}
        className="mt-1"
      />
      <label htmlFor={`cand-${c.url}`} className="flex-1 cursor-pointer">
        <div className="font-medium">{c.title}</div>
        <div className="break-all text-xs text-muted-foreground">{c.url}</div>
        {showReason && <div className="text-xs text-muted-foreground">{c.reason}</div>}
        <div className="text-xs text-muted-foreground">score {c.score.toFixed(2)}</div>
      </label>
    </li>
  );

  return (
    <div className="space-y-2">
      {high.length > 0 && (
        <ul role="list" className="space-y-1">
          {high.map((c) => renderRow(c, true))}
        </ul>
      )}
      {low.length > 0 && (
        <div>
          {!expanded ? (
            <button
              type="button"
              className="text-sm text-muted-foreground underline"
              onClick={() => setExpanded(true)}
            >
              Show {low.length} more candidate{low.length === 1 ? '' : 's'}
            </button>
          ) : (
            <ul role="list" className="space-y-1">
              {low.map((c) => renderRow(c, false))}
            </ul>
          )}
        </div>
      )}
      {high.length === 0 && low.length === 0 && (
        <p className="text-sm text-muted-foreground">No candidates found.</p>
      )}
    </div>
  );
}
