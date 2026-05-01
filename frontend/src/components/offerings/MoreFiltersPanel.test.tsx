import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MoreFiltersPanel } from './MoreFiltersPanel';
import { defaultFilterState } from '@/lib/offeringsFilters';
import type { FilterState } from '@/lib/types';

const defaultState: FilterState = defaultFilterState([1, 2]);

describe('MoreFiltersPanel', () => {
  it('collapsed by default: inner controls not visible when isOpen={false}', () => {
    const { container } = render(
      <MoreFiltersPanel
        value={defaultState}
        onChange={() => {}}
        programTypeOptions={['soccer', 'basketball']}
        isOpen={false}
        onToggle={() => {}}
      />,
    );
    // When <details> is not open, its children are hidden; we verify the
    // checkbox for "Hide muted" is not visible.
    const hideMutedCheckbox = container.querySelector('input[name="hideMuted"]');
    if (hideMutedCheckbox) {
      // Element exists but may not be visible; getComputedStyle would show display:none or similar
      // For <details>, we can check the open attribute
    }
    const details = container.querySelector('details');
    expect(details).toHaveProperty('open', false);
  });

  it('toggling an inner control mutates state via onChange', async () => {
    const user = userEvent.setup();
    let lastValue: FilterState | null = null;
    const handleChange = (next: FilterState) => {
      lastValue = next;
    };
    render(
      <MoreFiltersPanel
        value={defaultState}
        onChange={handleChange}
        programTypeOptions={['soccer', 'basketball']}
        isOpen={true}
        onToggle={() => {}}
      />,
    );
    // Click the "Watchlist only" checkbox
    const watchlistCheckbox = screen.getByLabelText(/Watchlist only/i) as HTMLInputElement;
    await user.click(watchlistCheckbox);
    // Verify onChange was called with watchlistOnly=true
    expect(lastValue).not.toBeNull();
    expect(lastValue!.watchlistOnly).toBe(true);
    // Verify other state unchanged
    expect(lastValue!.selectedKidIds).toEqual(defaultState.selectedKidIds);
    expect(lastValue!.minScore).toBe(defaultState.minScore);
  });

  it('days chip toggle: clicking mon chip mutates state', async () => {
    const user = userEvent.setup();
    let lastValue: FilterState | null = null;
    const handleChange = (next: FilterState) => {
      lastValue = next;
    };
    render(
      <MoreFiltersPanel
        value={defaultState}
        onChange={handleChange}
        programTypeOptions={['soccer']}
        isOpen={true}
        onToggle={() => {}}
      />,
    );
    // Click the "Mon" chip button
    const monButton = screen.getByRole('button', { name: /Mon/i });
    await user.click(monButton);
    // Verify onChange was called with 'mon' in days
    expect(lastValue).not.toBeNull();
    expect(lastValue!.days).toContain('mon');
  });

  it('Reset button clears all 8 secondary filters back to defaults but preserves primary filters', async () => {
    const user = userEvent.setup();
    let lastValue: FilterState | null = null;
    const handleChange = (next: FilterState) => {
      lastValue = next;
    };
    // Start with a state where all secondary filters are set
    const statefulValue: FilterState = {
      ...defaultState,
      hideMuted: false,
      programTypes: ['soccer'],
      days: ['mon', 'wed'],
      regTiming: 'open_now',
      timeOfDayMin: '09:00',
      timeOfDayMax: '17:00',
      maxDistanceMi: 5,
      ageMin: 6,
      ageMax: 12,
      watchlistOnly: true,
    };
    render(
      <MoreFiltersPanel
        value={statefulValue}
        onChange={handleChange}
        programTypeOptions={['soccer']}
        isOpen={true}
        onToggle={() => {}}
      />,
    );
    // Click the Reset button
    const resetButton = screen.getByRole('button', { name: /Reset secondary filters/i });
    await user.click(resetButton);
    // Verify all 8 secondary filters reset to defaults
    expect(lastValue).not.toBeNull();
    expect(lastValue!.hideMuted).toBe(true);
    expect(lastValue!.programTypes).toEqual([]);
    expect(lastValue!.days).toEqual([]);
    expect(lastValue!.regTiming).toBe('any');
    expect(lastValue!.timeOfDayMin).toBeNull();
    expect(lastValue!.timeOfDayMax).toBeNull();
    expect(lastValue!.maxDistanceMi).toBeNull();
    expect(lastValue!.ageMin).toBeNull();
    expect(lastValue!.ageMax).toBeNull();
    expect(lastValue!.watchlistOnly).toBe(false);
    // Verify primary filters and moreFiltersOpen unchanged
    expect(lastValue!.selectedKidIds).toEqual(statefulValue.selectedKidIds);
    expect(lastValue!.minScore).toBe(statefulValue.minScore);
    expect(lastValue!.sort).toBe(statefulValue.sort);
    expect(lastValue!.moreFiltersOpen).toBe(statefulValue.moreFiltersOpen);
  });
});
