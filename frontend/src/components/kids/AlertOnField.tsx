const KEYS = [
  { key: 'new_match', label: 'New matches' },
  { key: 'watchlist_hit', label: 'Watchlist hits' },
  { key: 'reg_opens', label: 'Registration opens' },
] as const;

interface Props {
  value: Record<string, boolean>;
  onChange: (value: Record<string, boolean>) => void;
}

export function AlertOnField({ value, onChange }: Props) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Alert types</legend>
      {KEYS.map(({ key, label }) => (
        <label key={key} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value[key] !== false}
            onChange={(e) => onChange({ ...value, [key]: e.target.checked })}
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}
