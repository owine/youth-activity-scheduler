import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchoolYearRangesField } from './SchoolYearRangesField';

describe('SchoolYearRangesField', () => {
  it('renders chip row and "+ Add school year range" button', () => {
    render(<SchoolYearRangesField value={[]} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /\+ Add school year range/ })).toBeInTheDocument();
  });

  it('renders no chips initially when value is empty', () => {
    render(<SchoolYearRangesField value={[]} onChange={vi.fn()} />);
    const removeButtons = screen.queryAllByRole('button', { name: /Remove range/ });
    expect(removeButtons).toHaveLength(0);
  });

  it('renders existing ranges as chips', () => {
    render(
      <SchoolYearRangesField
        value={[{ start: '2025-09-01', end: '2025-12-20' }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Remove range 0/)).toBeInTheDocument();
  });

  it('renders multiple ranges as chips', () => {
    render(
      <SchoolYearRangesField
        value={[
          { start: '2025-09-01', end: '2025-12-20' },
          { start: '2026-01-05', end: '2026-06-15' },
        ]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Remove range 0/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Remove range 1/)).toBeInTheDocument();
  });

  it('clicking "+ Add school year range" opens picker', async () => {
    render(<SchoolYearRangesField value={[]} onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /\+ Add school year range/ }));
    // Picker should now be visible with Cancel and Add buttons
    expect(screen.getByRole('button', { name: /^Cancel$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Add$/ })).toBeInTheDocument();
  });

  it('clicking Cancel closes picker and does not call onChange', async () => {
    const onChange = vi.fn();
    render(<SchoolYearRangesField value={[]} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /\+ Add school year range/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Cancel$/ }));
    expect(onChange).not.toHaveBeenCalled();
    // Button should be visible again
    expect(screen.getByRole('button', { name: /\+ Add school year range/ })).toBeInTheDocument();
  });

  it('Add button is disabled when range is incomplete', async () => {
    render(<SchoolYearRangesField value={[]} onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /\+ Add school year range/ }));
    const addButton = screen.getByRole('button', { name: /^Add$/ });
    expect(addButton).toBeDisabled();
  });

  it('clicking × removes a range chip', async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <SchoolYearRangesField
        value={[
          { start: '2025-09-01', end: '2025-12-20' },
          { start: '2026-01-05', end: '2026-06-15' },
        ]}
        onChange={onChange}
      />,
    );
    const removeButtons = screen.getAllByRole('button', { name: /Remove range/ });
    const firstButton = removeButtons[0];
    if (firstButton) {
      await userEvent.click(firstButton);
    }
    expect(onChange).toHaveBeenCalledWith([{ start: '2026-01-05', end: '2026-06-15' }]);
    rerender(
      <SchoolYearRangesField
        value={[{ start: '2026-01-05', end: '2026-06-15' }]}
        onChange={onChange}
      />,
    );
    // Should only have one remove button left
    const remainingRemoveButtons = screen.queryAllByRole('button', { name: /Remove range/ });
    expect(remainingRemoveButtons).toHaveLength(1);
  });

  it('renders error message when provided', () => {
    render(
      <SchoolYearRangesField value={[]} onChange={vi.fn()} error="Please add at least one range" />,
    );
    expect(screen.getByText('Please add at least one range')).toBeInTheDocument();
  });

  it('picker closes after canceling', async () => {
    const onChange = vi.fn();
    render(<SchoolYearRangesField value={[]} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /\+ Add school year range/ }));
    // Picker should be visible with Cancel button
    const cancelButton = screen.getByRole('button', { name: /^Cancel$/ });
    expect(cancelButton).toBeInTheDocument();
    await userEvent.click(cancelButton);
    // Button should reappear after cancel
    expect(screen.getByRole('button', { name: /\+ Add school year range/ })).toBeInTheDocument();
  });
});
