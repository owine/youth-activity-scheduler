import { Button } from '@/components/ui/button';
import type { FilterState } from '@/lib/types';

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
  programTypeOptions: string[];
  isOpen: boolean;
  onToggle: (next: boolean) => void;
}

function countActiveFilters(value: FilterState): number {
  let count = 0;
  // hideMuted !== true → +1 (default is true; counts as "active" if FALSE)
  if (value.hideMuted !== true) count++;
  // programTypes.length > 0 → +1
  if (value.programTypes.length > 0) count++;
  // days.length > 0 → +1
  if (value.days.length > 0) count++;
  // regTiming !== 'any' → +1
  if (value.regTiming !== 'any') count++;
  // timeOfDayMin !== null || timeOfDayMax !== null → +1
  if (value.timeOfDayMin !== null || value.timeOfDayMax !== null) count++;
  // maxDistanceMi !== null → +1
  if (value.maxDistanceMi !== null) count++;
  // ageMin !== null || ageMax !== null → +1
  if (value.ageMin !== null || value.ageMax !== null) count++;
  // watchlistOnly → +1
  if (value.watchlistOnly) count++;
  return count;
}

export function MoreFiltersPanel({ value, onChange, programTypeOptions, isOpen, onToggle }: Props) {
  const activeCount = countActiveFilters(value);

  const handleResetSecondaryFilters = () => {
    onChange({
      ...value,
      hideMuted: true,
      programTypes: [],
      days: [],
      regTiming: 'any',
      timeOfDayMin: null,
      timeOfDayMax: null,
      maxDistanceMi: null,
      ageMin: null,
      ageMax: null,
      watchlistOnly: false,
    });
  };

  const toggleDay = (day: (typeof DAYS)[number]) => {
    const newDays = value.days.includes(day)
      ? value.days.filter((d) => d !== day)
      : [...value.days, day];
    onChange({ ...value, days: newDays });
  };

  return (
    <details
      open={isOpen}
      onToggle={(e) => onToggle((e.target as HTMLDetailsElement).open)}
      className="w-full"
    >
      <summary className="cursor-pointer select-none font-semibold hover:text-primary">
        More filters ({activeCount} active)
      </summary>

      <div className="mt-4 space-y-4">
        {/* 2-column grid for the 8 controls */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* 1. Hide muted */}
          <div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                name="hideMuted"
                checked={value.hideMuted}
                onChange={(e) => onChange({ ...value, hideMuted: e.target.checked })}
                className="size-4 cursor-pointer rounded border border-input"
              />
              <span className="text-sm">Hide muted</span>
            </label>
          </div>

          {/* 2. Program type */}
          <div>
            <label className="block text-sm font-medium mb-1">Program type</label>
            <select
              multiple
              value={value.programTypes}
              onChange={(e) => {
                const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
                onChange({ ...value, programTypes: selected });
              }}
              className="w-full min-h-[100px] rounded border border-input bg-background px-3 py-2 text-sm"
            >
              {programTypeOptions.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground mt-1">Ctrl/Cmd+click to select multiple</p>
          </div>

          {/* 3. Days of week */}
          <div>
            <label className="block text-sm font-medium mb-2">Days of week</label>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((day) => (
                <button
                  key={day}
                  type="button"
                  onClick={() => toggleDay(day)}
                  className={`rounded px-3 py-1.5 text-sm font-medium transition ${
                    value.days.includes(day)
                      ? 'bg-primary text-primary-foreground'
                      : 'border border-input bg-background hover:bg-accent'
                  }`}
                >
                  {day.charAt(0).toUpperCase() + day.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* 4. Reg timing */}
          <div>
            <label className="block text-sm font-medium mb-2">Registration timing</label>
            <div className="space-y-2">
              {(['any', 'opens_this_week', 'open_now', 'closed'] as const).map((option) => (
                <label key={option} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="regTiming"
                    value={option}
                    checked={value.regTiming === option}
                    onChange={() => onChange({ ...value, regTiming: option })}
                    className="size-4 cursor-pointer"
                  />
                  <span className="text-sm">
                    {option === 'any' && 'Any time'}
                    {option === 'opens_this_week' && 'Opens this week'}
                    {option === 'open_now' && 'Open now'}
                    {option === 'closed' && 'Closed'}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* 5. Time-of-day range */}
          <div>
            <label className="block text-sm font-medium mb-2">Time of day</label>
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <label className="block text-xs text-muted-foreground mb-1">Start</label>
                <input
                  type="time"
                  value={value.timeOfDayMin ?? ''}
                  onChange={(e) => onChange({ ...value, timeOfDayMin: e.target.value || null })}
                  className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
                />
              </div>
              <div className="flex-1">
                <label className="block text-xs text-muted-foreground mb-1">End</label>
                <input
                  type="time"
                  value={value.timeOfDayMax ?? ''}
                  onChange={(e) => onChange({ ...value, timeOfDayMax: e.target.value || null })}
                  className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
                />
              </div>
            </div>
          </div>

          {/* 6. Distance */}
          <div>
            <label className="block text-sm font-medium mb-2">Distance</label>
            <div className="flex gap-2">
              <div className="flex-1">
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={value.maxDistanceMi ?? ''}
                  onChange={(e) => {
                    const val = e.target.value ? parseInt(e.target.value, 10) : null;
                    onChange({ ...value, maxDistanceMi: val });
                  }}
                  placeholder="Max miles"
                  className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
                />
              </div>
              {value.maxDistanceMi !== null && (
                <button
                  type="button"
                  onClick={() => onChange({ ...value, maxDistanceMi: null })}
                  className="rounded border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {/* 7. Age range */}
          <div>
            <label className="block text-sm font-medium mb-2">Age range</label>
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="block text-xs text-muted-foreground mb-1">Min</label>
                  <input
                    type="number"
                    min="0"
                    max="120"
                    value={value.ageMin ?? ''}
                    onChange={(e) => {
                      const val = e.target.value ? parseInt(e.target.value, 10) : null;
                      onChange({ ...value, ageMin: val });
                    }}
                    placeholder="Min age"
                    className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
                  />
                </div>
                <div className="flex-1">
                  <label className="block text-xs text-muted-foreground mb-1">Max</label>
                  <input
                    type="number"
                    min="0"
                    max="120"
                    value={value.ageMax ?? ''}
                    onChange={(e) => {
                      const val = e.target.value ? parseInt(e.target.value, 10) : null;
                      onChange({ ...value, ageMax: val });
                    }}
                    placeholder="Max age"
                    className="w-full rounded border border-input bg-background px-2 py-1.5 text-sm"
                  />
                </div>
              </div>
              {value.ageMin !== null && value.ageMax !== null && value.ageMin > value.ageMax && (
                <p className="text-xs text-destructive">
                  Min age must be less than or equal to max age
                </p>
              )}
            </div>
          </div>

          {/* 8. Watchlist only */}
          <div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                name="watchlistOnly"
                checked={value.watchlistOnly}
                onChange={(e) => onChange({ ...value, watchlistOnly: e.target.checked })}
                className="size-4 cursor-pointer rounded border border-input"
              />
              <span className="text-sm">Watchlist only</span>
            </label>
          </div>
        </div>

        {/* Reset button */}
        <div className="mt-6 flex justify-start">
          <Button variant="outline" onClick={handleResetSecondaryFilters}>
            Reset secondary filters
          </Button>
        </div>
      </div>
    </details>
  );
}
