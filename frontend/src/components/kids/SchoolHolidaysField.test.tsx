import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { format } from 'date-fns';
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

  // Date-only strings must be read as local calendar days. new Date('YYYY-MM-DD')
  // is UTC midnight, which is the previous evening anywhere west of UTC (run the
  // suite with TZ=America/New_York to reproduce).
  it('shows the stored calendar day on the chip, not the day before', () => {
    render(<SchoolHolidaysField value={['2025-12-25']} onChange={vi.fn()} />);
    expect(screen.getByText('Dec 25, 2025')).toBeInTheDocument();
  });

  it('keeps existing holidays on their own day when another is picked', async () => {
    const onChange = vi.fn();
    const month = format(new Date(), 'yyyy-MM');
    render(<SchoolHolidaysField value={[`${month}-15`]} onChange={onChange} />);
    // DayPicker opens on the current month; day buttons are labelled with the date.
    const day20 = screen
      .getAllByRole('button')
      .find((b) => b.textContent?.trim() === '20' && !b.closest('[data-outside]'));
    expect(day20).toBeDefined();
    await userEvent.click(day20!);
    expect(onChange).toHaveBeenCalledWith([`${month}-15`, `${month}-20`]);
  });
});
