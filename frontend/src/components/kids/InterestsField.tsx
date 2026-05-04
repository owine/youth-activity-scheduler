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
      <label htmlFor="interests-input" className="block text-sm font-medium">
        Interests
      </label>
      <p className="text-xs text-muted-foreground">
        Add at least one — without interests, no offerings will match this kid. Examples: soccer,
        tennis, baseball, swim, gymnastics, art, music, multisport.
      </p>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
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
      )}
      <input
        id="interests-input"
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
        placeholder="Type an interest and press Enter (e.g. tennis)"
        aria-invalid={error ? 'true' : undefined}
        className="mt-1 block w-full rounded border border-input px-3 py-2"
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
