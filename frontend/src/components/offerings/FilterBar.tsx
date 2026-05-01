import type { FilterState, KidBrief } from '@/lib/types';
import { MoreFiltersPanel } from './MoreFiltersPanel';

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
  kids: KidBrief[];
  programTypeOptions: string[];
}

export function FilterBar({ value, onChange, kids, programTypeOptions }: Props) {
  const toggleKid = (kidId: number) => {
    const newSelectedKidIds = value.selectedKidIds.includes(kidId)
      ? value.selectedKidIds.filter((id) => id !== kidId)
      : [...value.selectedKidIds, kidId];
    onChange({ ...value, selectedKidIds: newSelectedKidIds });
  };

  const selectAllKids = () => {
    onChange({ ...value, selectedKidIds: kids.map((k) => k.id) });
  };

  const showSelectAll = value.selectedKidIds.length < kids.length;

  return (
    <div className="space-y-4 rounded-lg border border-input bg-card p-4">
      {/* Primary filters row */}
      <div className="flex flex-wrap items-center gap-6">
        {/* 1. Kids chip group */}
        <div className="flex flex-wrap items-center gap-2">
          {kids.map((kid) => (
            <button
              key={kid.id}
              type="button"
              onClick={() => toggleKid(kid.id)}
              className={`rounded-full px-3 py-1 text-sm font-medium transition ${
                value.selectedKidIds.includes(kid.id)
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-input bg-background hover:bg-accent'
              }`}
            >
              {kid.name}
            </button>
          ))}
          {showSelectAll && (
            <button
              type="button"
              onClick={selectAllKids}
              className="ml-2 text-sm text-primary hover:underline"
            >
              Select all
            </button>
          )}
        </div>

        {/* 2. Min score slider */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium">Min score:</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={value.minScore}
            onChange={(e) => onChange({ ...value, minScore: parseFloat(e.target.value) })}
            className="w-24"
          />
          <span className="text-sm font-mono">{value.minScore.toFixed(2)}</span>
        </div>

        {/* 3. Sort dropdown */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium">Sort:</label>
          <select
            value={value.sort}
            onChange={(e) =>
              onChange({
                ...value,
                sort: e.target.value as 'best_score' | 'soonest_start' | 'soonest_reg',
              })
            }
            className="rounded border border-input bg-background px-2 py-1 text-sm"
          >
            <option value="best_score">Best score</option>
            <option value="soonest_start">Soonest start</option>
            <option value="soonest_reg">Soonest registration</option>
          </select>
        </div>
      </div>

      {/* MoreFiltersPanel */}
      <MoreFiltersPanel
        value={value}
        onChange={onChange}
        programTypeOptions={programTypeOptions}
        isOpen={value.moreFiltersOpen}
        onToggle={(o) => onChange({ ...value, moreFiltersOpen: o })}
      />
    </div>
  );
}
