import { Button } from '@/components/ui/button';
import type { AlertStatus, KidBrief, OutboxFilterState } from '@/lib/types';

const ALERT_TYPES = [
  'watchlist_hit',
  'new_match',
  'reg_opens_24h',
  'reg_opens_1h',
  'reg_opens_now',
  'schedule_posted',
  'crawl_failed',
  'digest',
  'site_stagnant',
  'no_matches_for_kid',
  'push_cap',
] as const;
const STATUS_OPTIONS: (AlertStatus | null)[] = [null, 'pending', 'sent', 'skipped'];

interface Props {
  value: OutboxFilterState;
  onChange: (next: OutboxFilterState) => void;
  kids: KidBrief[];
}

export function OutboxFilterBar({ value, onChange, kids }: Props) {
  const update = (patch: Partial<OutboxFilterState>) => onChange({ ...value, ...patch, page: 0 });

  const handleClear = () =>
    onChange({
      kidId: null,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 0,
    });

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-card p-3">
      <div>
        <label
          htmlFor="filter-kid"
          className="block text-xs font-medium uppercase text-muted-foreground"
        >
          Kid
        </label>
        <select
          id="filter-kid"
          value={value.kidId ?? ''}
          onChange={(e) => update({ kidId: e.target.value ? Number(e.target.value) : null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">Any</option>
          {kids.map((k) => (
            <option key={k.id} value={k.id}>
              {k.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          htmlFor="filter-type"
          className="block text-xs font-medium uppercase text-muted-foreground"
        >
          Type
        </label>
        <select
          id="filter-type"
          value={value.type ?? ''}
          onChange={(e) => update({ type: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">Any</option>
          {ALERT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <fieldset>
        <legend className="block text-xs font-medium uppercase text-muted-foreground">
          Status
        </legend>
        <div className="flex gap-2 text-sm">
          {STATUS_OPTIONS.map((s) => (
            <label key={s ?? 'any'} className="flex items-center gap-1">
              <input
                type="radio"
                name="status"
                checked={value.status === s}
                onChange={() => update({ status: s })}
              />
              {s ?? 'any'}
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <label
          htmlFor="filter-since"
          className="block text-xs font-medium uppercase text-muted-foreground"
        >
          Since
        </label>
        <input
          id="filter-since"
          type="date"
          value={value.since ?? ''}
          onChange={(e) => update({ since: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </div>
      <div>
        <label
          htmlFor="filter-until"
          className="block text-xs font-medium uppercase text-muted-foreground"
        >
          Until
        </label>
        <input
          id="filter-until"
          type="date"
          value={value.until ?? ''}
          onChange={(e) => update({ until: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </div>
      <Button type="button" variant="outline" onClick={handleClear}>
        Clear
      </Button>
    </div>
  );
}
