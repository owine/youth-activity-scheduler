import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InterestsField } from './InterestsField';

describe('InterestsField', () => {
  it('renders all current interests as chips with × buttons', () => {
    render(<InterestsField value={['Baseball', 'Soccer']} onChange={vi.fn()} />);
    expect(screen.getByText('Baseball')).toBeInTheDocument();
    expect(screen.getByText('Soccer')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove Baseball')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove Soccer')).toBeInTheDocument();
  });

  it('renders input placeholder', () => {
    render(<InterestsField value={[]} onChange={vi.fn()} />);
    expect(
      screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)'),
    ).toBeInTheDocument();
  });

  it('typing + Enter adds a chip and clears input', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={[]} onChange={onChange} />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    await userEvent.type(input, 'Tennis');
    await userEvent.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith(['Tennis']);
    expect(input).toHaveValue('');
  });

  it('typing + comma adds a chip and clears input', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={[]} onChange={onChange} />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    await userEvent.type(input, 'Basketball,');
    expect(onChange).toHaveBeenCalledWith(['Basketball']);
    expect(input).toHaveValue('');
  });

  it('blur on non-empty input adds chip', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={[]} onChange={onChange} />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    await userEvent.type(input, 'Volleyball');
    await userEvent.click(document.body);
    expect(onChange).toHaveBeenCalledWith(['Volleyball']);
  });

  it('empty trimmed input does not add chip', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={[]} onChange={onChange} />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    await userEvent.type(input, '   ');
    await userEvent.keyboard('{Enter}');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('duplicate (case-insensitive) does not add', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={['Baseball']} onChange={onChange} />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    await userEvent.type(input, 'baseball');
    await userEvent.keyboard('{Enter}');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('click × removes a chip', async () => {
    const onChange = vi.fn();
    render(<InterestsField value={['Baseball', 'Soccer']} onChange={onChange} />);
    await userEvent.click(screen.getByLabelText('Remove Baseball'));
    expect(onChange).toHaveBeenCalledWith(['Soccer']);
  });

  it('renders error message when provided', () => {
    render(<InterestsField value={[]} onChange={vi.fn()} error="This field is required" />);
    expect(screen.getByText('This field is required')).toBeInTheDocument();
  });

  it('sets aria-invalid on input when error is present', () => {
    render(<InterestsField value={[]} onChange={vi.fn()} error="This field is required" />);
    const input = screen.getByPlaceholderText('Type an interest and press Enter (e.g. tennis)');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });
});
