import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AlertOnField } from './AlertOnField';

describe('AlertOnField', () => {
  it('renders 3 toggles with correct labels', () => {
    render(<AlertOnField value={{}} onChange={vi.fn()} />);
    expect(screen.getByLabelText('New matches')).toBeInTheDocument();
    expect(screen.getByLabelText('Watchlist hits')).toBeInTheDocument();
    expect(screen.getByLabelText('Registration opens')).toBeInTheDocument();
  });

  it('renders fieldset with "Alert types" legend', () => {
    render(<AlertOnField value={{}} onChange={vi.fn()} />);
    expect(screen.getByText('Alert types')).toBeInTheDocument();
  });

  it('all checkboxes default checked when value is {}', () => {
    render(<AlertOnField value={{}} onChange={vi.fn()} />);
    expect(screen.getByLabelText('New matches')).toBeChecked();
    expect(screen.getByLabelText('Watchlist hits')).toBeChecked();
    expect(screen.getByLabelText('Registration opens')).toBeChecked();
  });

  it('checkbox reflects false value when explicitly set to false', () => {
    render(
      <AlertOnField
        value={{ new_match: false, watchlist_hit: true, reg_opens: true }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('New matches')).not.toBeChecked();
    expect(screen.getByLabelText('Watchlist hits')).toBeChecked();
    expect(screen.getByLabelText('Registration opens')).toBeChecked();
  });

  it('clicking a toggle calls onChange with updated value', async () => {
    const onChange = vi.fn();
    render(
      <AlertOnField
        value={{ new_match: true, watchlist_hit: true, reg_opens: true }}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText('New matches'));
    expect(onChange).toHaveBeenCalledWith({
      new_match: false,
      watchlist_hit: true,
      reg_opens: true,
    });
  });

  it('toggling from false to true works', async () => {
    const onChange = vi.fn();
    render(
      <AlertOnField
        value={{ new_match: false, watchlist_hit: true, reg_opens: true }}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText('New matches'));
    expect(onChange).toHaveBeenCalledWith({
      new_match: true,
      watchlist_hit: true,
      reg_opens: true,
    });
  });

  it('preserves other keys when toggling one', async () => {
    const onChange = vi.fn();
    const initialValue = {
      new_match: true,
      watchlist_hit: false,
      reg_opens: true,
      custom_key: true, // Should be preserved
    };
    render(<AlertOnField value={initialValue} onChange={onChange} />);
    await userEvent.click(screen.getByLabelText('Watchlist hits'));
    expect(onChange).toHaveBeenCalledWith({
      new_match: true,
      watchlist_hit: true,
      reg_opens: true,
      custom_key: true,
    });
  });
});
