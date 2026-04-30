import { useState } from 'react';

interface Props {
  value: string[];
  onChange: (value: string[]) => void;
  error?: string;
}

export function InterestsField({ value, onChange, error }: Props) {
  const [input, setInput] = useState('');

  const add = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    if (value.some((v) => v.toLowerCase() === trimmed.toLowerCase())) return;
    onChange([...value, trimmed]);
    setInput('');
  };

  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <span
            key={`${v}-${i}`}
            className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs"
          >
            {v}
            <button type="button" aria-label={`Remove ${v}`} onClick={() => remove(i)}>
              ×
            </button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add(input);
          }
        }}
        onBlur={() => add(input)}
        placeholder="Type and press Enter (e.g., baseball)"
        aria-invalid={error ? 'true' : undefined}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
