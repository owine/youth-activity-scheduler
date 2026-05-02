import type { CombinedCalendarFilterState, KidBrief, CalendarEventKind } from '@/lib/types';
import { colorForKid } from '@/lib/calendarColors';

const ALL_TYPES: { kind: CalendarEventKind; label: string }[] = [
  { kind: 'enrollment', label: 'Enrollment' },
  { kind: 'unavailability', label: 'Unavailability' },
  { kind: 'match', label: 'Match' },
];

function isAtDefaults(f: CombinedCalendarFilterState): boolean {
  return f.kidIds === null && f.types === null && f.includeMatches === false;
}

interface Props {
  kids: readonly KidBrief[];
  filters: CombinedCalendarFilterState;
  onChange: (next: CombinedCalendarFilterState) => void;
  onClear: () => void;
}

export function CombinedCalendarFilters({ kids, filters, onChange, onClear }: Props) {
  const activeKids = kids.filter((k) => k.active);
  const selectedKidIds = filters.kidIds ?? activeKids.map((k) => k.id);
  const selectedTypes: CalendarEventKind[] = filters.types ?? ALL_TYPES.map((t) => t.kind);

  const toggleKid = (id: number) => {
    const next = selectedKidIds.includes(id)
      ? selectedKidIds.filter((k) => k !== id)
      : [...selectedKidIds, id].sort((a, b) => a - b);
    const allSelected =
      next.length === activeKids.length && activeKids.every((k) => next.includes(k.id));
    onChange({ ...filters, kidIds: allSelected ? null : next });
  };

  const toggleType = (kind: CalendarEventKind) => {
    const next = selectedTypes.includes(kind)
      ? selectedTypes.filter((t) => t !== kind)
      : [...selectedTypes, kind];
    const allSelected = ALL_TYPES.every((t) => next.includes(t.kind));
    onChange({ ...filters, types: allSelected ? null : next });
  };

  return (
    <div className="flex flex-wrap items-center gap-4 text-sm">
      <div className="flex flex-wrap gap-3" aria-label="Kid filters">
        {activeKids.map((k) => {
          const color = colorForKid(k.id);
          return (
            <label key={k.id} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={selectedKidIds.includes(k.id)}
                onChange={() => toggleKid(k.id)}
                aria-label={k.name}
              />
              <span className={`inline-block h-3 w-3 rounded-sm ${color.bg}`} aria-hidden />
              <span>{k.name}</span>
            </label>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-3" aria-label="Type filters">
        {ALL_TYPES.map((t) => (
          <label key={t.kind} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={selectedTypes.includes(t.kind)}
              onChange={() => toggleType(t.kind)}
              aria-label={t.label}
            />
            <span>{t.label}</span>
          </label>
        ))}
      </div>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={filters.includeMatches}
          onChange={(e) => onChange({ ...filters, includeMatches: e.target.checked })}
        />
        <span>Include matches</span>
      </label>
      {!isAtDefaults(filters) && (
        <button
          type="button"
          onClick={onClear}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
