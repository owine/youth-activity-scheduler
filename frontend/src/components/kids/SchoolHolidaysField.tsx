import { DayPicker } from 'react-day-picker';
import { format } from 'date-fns';

interface Props {
  value: string[];
  onChange: (value: string[]) => void;
  error?: string;
}

export function SchoolHolidaysField({ value, onChange, error }: Props) {
  const dates = value.map((s) => new Date(s));

  const handleSelect = (selected: Date[] | undefined) => {
    onChange((selected ?? []).map((d) => format(d, 'yyyy-MM-dd')));
  };

  return (
    <div className="space-y-2">
      <DayPicker mode="multiple" selected={dates} onSelect={handleSelect} />
      <div className="flex flex-wrap gap-1">
        {value.map((d, i) => (
          <span
            key={d}
            className="inline-flex items-center gap-1 rounded bg-accent px-2 py-1 text-xs"
          >
            {format(new Date(d), 'MMM d, yyyy')}
            <button
              type="button"
              aria-label={`Remove ${d}`}
              onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
