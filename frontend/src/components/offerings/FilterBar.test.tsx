import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterBar } from './FilterBar';
import { defaultFilterState } from '@/lib/offeringsFilters';
import type { FilterState, KidBrief } from '@/lib/types';

const kids: KidBrief[] = [
  { id: 1, name: 'Sam', dob: '2018-01-01', interests: [], active: true },
  { id: 2, name: 'Alex', dob: '2019-06-15', interests: [], active: true },
];

const programTypeOptions = ['soccer', 'basketball', 'swim'];

const defaultState: FilterState = defaultFilterState([1, 2]);

describe('FilterBar', () => {
  it('renders 3 primary controls + MoreFiltersPanel', () => {
    const { container } = render(
      <FilterBar
        value={defaultState}
        onChange={() => {}}
        kids={kids}
        programTypeOptions={programTypeOptions}
      />,
    );
    // Kids chip group should be visible
    expect(screen.getByRole('button', { name: /Sam/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Alex/i })).toBeInTheDocument();
    // Min score slider should be visible
    expect(container.querySelector('input[type="range"]')).toBeInTheDocument();
    // Sort dropdown should be visible
    expect(container.querySelector('select')).toBeInTheDocument();
    // MoreFiltersPanel should be present as a child
    expect(container.querySelector('details')).toBeInTheDocument();
  });

  it('toggling a kid chip mutates selectedKidIds via onChange', async () => {
    const user = userEvent.setup();
    let lastValue: FilterState | null = null;
    const handleChange = (next: FilterState) => {
      lastValue = next;
    };
    // Both kids selected initially
    const state: FilterState = { ...defaultState, selectedKidIds: [1, 2] };
    render(
      <FilterBar
        value={state}
        onChange={handleChange}
        kids={kids}
        programTypeOptions={programTypeOptions}
      />,
    );
    // Click Sam's chip to deselect
    const samChip = screen.getByRole('button', { name: /Sam/i });
    await user.click(samChip);
    // Verify onChange was called with selectedKidIds === [2]
    expect(lastValue).not.toBeNull();
    expect(lastValue!.selectedKidIds).toEqual([2]);
  });

  it('Select all link appears when selectedKidIds.length < kids.length and clicking it selects all', async () => {
    const user = userEvent.setup();
    let lastValue: FilterState | null = null;
    const handleChange = (next: FilterState) => {
      lastValue = next;
    };
    // Only kid 1 selected initially
    const state: FilterState = { ...defaultState, selectedKidIds: [1] };
    render(
      <FilterBar
        value={state}
        onChange={handleChange}
        kids={kids}
        programTypeOptions={programTypeOptions}
      />,
    );
    // "Select all" link should be visible
    const selectAllLink = screen.getByRole('button', { name: /Select all/i });
    expect(selectAllLink).toBeInTheDocument();
    // Click it
    await user.click(selectAllLink);
    // Verify onChange was called with all kid IDs
    expect(lastValue).not.toBeNull();
    expect(lastValue!.selectedKidIds).toEqual([1, 2]);
  });
});
