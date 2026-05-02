import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutboxFilterBar } from './OutboxFilterBar';
import type { OutboxFilterState, KidBrief } from '@/lib/types';

const baseFilters: OutboxFilterState = {
  kidId: null,
  type: null,
  status: null,
  since: null,
  until: null,
  page: 0,
};
const kids: KidBrief[] = [
  { id: 1, name: 'Sam', dob: '2019-01-01', interests: [], active: true },
  { id: 2, name: 'Alex', dob: '2020-01-01', interests: [], active: true },
];

describe('OutboxFilterBar', () => {
  it('renders kid select + type select + status radio + since/until inputs + Clear', () => {
    render(<OutboxFilterBar value={baseFilters} onChange={vi.fn()} kids={kids} />);
    expect(screen.getByLabelText(/kid/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/since/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/until/i)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /any/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
  });

  it('toggling status radio fires onChange with new status + page reset to 0', async () => {
    const onChange = vi.fn();
    render(<OutboxFilterBar value={{ ...baseFilters, page: 5 }} onChange={onChange} kids={kids} />);
    await userEvent.click(screen.getByRole('radio', { name: /sent/i }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'sent', page: 0 }));
  });

  it('setting since date fires onChange with the date string', async () => {
    const onChange = vi.fn();
    render(<OutboxFilterBar value={baseFilters} onChange={onChange} kids={kids} />);
    const since = screen.getByLabelText(/since/i);
    await userEvent.type(since, '2026-04-01');
    expect(onChange).toHaveBeenCalled();
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.since).toBe('2026-04-01');
  });

  it('Clear button resets all filters to defaults', async () => {
    const onChange = vi.fn();
    const dirty: OutboxFilterState = {
      kidId: 1,
      type: 'new_match',
      status: 'sent',
      since: '2026-04-01',
      until: '2026-05-01',
      page: 3,
    };
    render(<OutboxFilterBar value={dirty} onChange={onChange} kids={kids} />);
    await userEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith({
      kidId: null,
      type: null,
      status: null,
      since: null,
      until: null,
      page: 0,
    });
  });
});
