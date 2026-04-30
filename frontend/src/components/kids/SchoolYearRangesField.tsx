import { useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { DayPicker } from 'react-day-picker';
import { format } from 'date-fns';

interface YearRange {
  start: string;
  end: string;
}

interface Props {
  value: YearRange[];
  onChange: (value: YearRange[]) => void;
  error?: string;
}

export function SchoolYearRangesField({ value, onChange, error }: Props) {
  const [draft, setDraft] = useState<DateRange | undefined>();
  const [open, setOpen] = useState(false);

  const commit = () => {
    if (!draft?.from || !draft?.to) return;
    onChange([
      ...value,
      {
        start: format(draft.from, 'yyyy-MM-dd'),
        end: format(draft.to, 'yyyy-MM-dd'),
      },
    ]);
    setDraft(undefined);
    setOpen(false);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {value.map((r, i) => (
          <span
            key={`${r.start}-${r.end}`}
            className="inline-flex items-center gap-1 rounded bg-accent px-2 py-1 text-xs"
          >
            {format(new Date(r.start), 'MMM d, yyyy')} → {format(new Date(r.end), 'MMM d, yyyy')}
            <button
              type="button"
              aria-label={`Remove range ${i}`}
              onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} className="text-sm underline">
          + Add school year range
        </button>
      )}
      {open && (
        <div className="rounded-md border border-border p-2">
          <DayPicker mode="range" selected={draft} onSelect={setDraft} />
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(undefined);
                setOpen(false);
              }}
            >
              Cancel
            </button>
            <button type="button" disabled={!draft?.from || !draft?.to} onClick={commit}>
              Add
            </button>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
