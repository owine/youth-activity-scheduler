import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CombinedCalendarFilters } from './CombinedCalendarFilters';
import type { KidBrief, CombinedCalendarFilterState } from '@/lib/types';

const sam: KidBrief = {
  id: 1,
  name: 'Sam',
  dob: '2019-05-01',
  interests: [],
  active: true,
};
const lila: KidBrief = {
  id: 2,
  name: 'Lila',
  dob: '2017-08-12',
  interests: [],
  active: true,
};
const allOn: CombinedCalendarFilterState = {
  kidIds: null,
  types: null,
  includeMatches: false,
};

describe('CombinedCalendarFilters', () => {
  it('renders one checkbox per kid, all checked when kidIds=null', () => {
    render(
      <CombinedCalendarFilters
        kids={[sam, lila]}
        filters={allOn}
        onChange={() => {}}
        onClear={() => {}}
      />,
    );
    expect(screen.getByLabelText('Sam')).toBeChecked();
    expect(screen.getByLabelText('Lila')).toBeChecked();
  });

  it('renders type checkboxes — all checked when types=null', () => {
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={allOn}
        onChange={() => {}}
        onClear={() => {}}
      />,
    );
    expect(screen.getByLabelText(/Enrollment/i)).toBeChecked();
    expect(screen.getByLabelText(/Unavailability/i)).toBeChecked();
    expect(screen.getByLabelText(/^Match$/i)).toBeChecked();
    expect(screen.getByLabelText(/Holiday/i)).toBeChecked();
  });

  it('toggling a kid checkbox invokes onChange with that kid removed', async () => {
    const onChange = vi.fn();
    render(
      <CombinedCalendarFilters
        kids={[sam, lila]}
        filters={allOn}
        onChange={onChange}
        onClear={() => {}}
      />,
    );
    await userEvent.click(screen.getByLabelText('Sam'));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kidIds: [2] }));
  });

  it('hides Clear button when filters are at defaults', () => {
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={allOn}
        onChange={() => {}}
        onClear={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: /Clear/i })).toBeNull();
  });

  it('shows Clear button when any filter is set', () => {
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={{ kidIds: [1], types: null, includeMatches: false }}
        onChange={() => {}}
        onClear={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /Clear/i })).toBeInTheDocument();
  });

  it('clicking Clear invokes onClear', async () => {
    const onClear = vi.fn();
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={{ kidIds: [1], types: null, includeMatches: false }}
        onChange={() => {}}
        onClear={onClear}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Clear/i }));
    expect(onClear).toHaveBeenCalled();
  });
});
