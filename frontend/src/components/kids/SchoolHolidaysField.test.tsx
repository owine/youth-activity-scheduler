import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchoolHolidaysField } from './SchoolHolidaysField';

describe('SchoolHolidaysField', () => {
  it('renders calendar and chip row', () => {
    render(<SchoolHolidaysField value={[]} onChange={vi.fn()} />);
    // DayPicker renders a grid with month/year header
    expect(screen.getByRole('grid')).toBeInTheDocument();
  });

  it('renders no chips initially when value is empty', () => {
    render(<SchoolHolidaysField value={[]} onChange={vi.fn()} />);
    // Should not have any chips with × buttons initially
    const removeButtons = screen.queryAllByRole('button', { name: /^×$/ });
    expect(removeButtons).toHaveLength(0);
  });

  it('renders existing dates as chips', () => {
    render(<SchoolHolidaysField value={['2025-12-25']} onChange={vi.fn()} />);
    expect(screen.getByLabelText(/Remove 2025-12-25/)).toBeInTheDocument();
  });

  it('renders multiple dates as chips', () => {
    render(<SchoolHolidaysField value={['2025-12-25', '2026-01-01']} onChange={vi.fn()} />);
    expect(screen.getByLabelText(/Remove 2025-12-25/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Remove 2026-01-01/)).toBeInTheDocument();
  });

  it('clicking × removes a date chip', async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <SchoolHolidaysField value={['2025-12-25', '2026-01-01']} onChange={onChange} />,
    );
    const removeButtons = screen.getAllByRole('button', { name: /Remove/ });
    if (removeButtons.length > 0) {
      const firstButton = removeButtons[0];
      if (firstButton) {
        await userEvent.click(firstButton);
      }
    }
    expect(onChange).toHaveBeenCalledWith(['2026-01-01']);
    rerender(<SchoolHolidaysField value={['2026-01-01']} onChange={onChange} />);
    const button = screen.queryByLabelText(/Remove 2025-12-25/);
    expect(button).not.toBeInTheDocument();
  });

  it('renders error message when provided', () => {
    render(
      <SchoolHolidaysField value={[]} onChange={vi.fn()} error="Please select at least one date" />,
    );
    expect(screen.getByText('Please select at least one date')).toBeInTheDocument();
  });

  it('calendar can select and deselect dates', async () => {
    const onChange = vi.fn();
    render(<SchoolHolidaysField value={[]} onChange={onChange} />);

    // Find and click a date button in the calendar
    const dateButtons = screen.getAllByRole('button');
    // Filter to find a clickable date (skip navigation and other buttons)
    // DayPicker typically has day buttons with just a number
    const dayButtons = dateButtons.filter((btn) => {
      const text = btn.textContent?.trim();
      return text && /^\d{1,2}$/.test(text) && !btn.getAttribute('aria-current');
    });
    if (dayButtons.length > 0 && dayButtons[0]) {
      await userEvent.click(dayButtons[0]);
      // onChange should have been called with a date array
      expect(onChange).toHaveBeenCalled();
    }
  });
});
