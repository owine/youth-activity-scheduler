import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MuteButton } from './MuteButton';
import { FOREVER_SENTINEL } from '@/lib/mute';

describe('MuteButton', () => {
  it('renders "Mute" when not muted (null)', () => {
    render(<MuteButton mutedUntil={null} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^mute$/i })).toBeInTheDocument();
  });

  it('renders "Mute" when mute timestamp is in the past', () => {
    const now = new Date();
    const past = new Date(now.getTime() - 86_400_000).toISOString();
    render(<MuteButton mutedUntil={past} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^mute$/i })).toBeInTheDocument();
  });

  it('renders "Muted until ..." when mute timestamp is in the future', () => {
    const now = new Date();
    const future = new Date(now.getTime() + 7 * 86_400_000).toISOString();
    render(<MuteButton mutedUntil={future} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /muted until/i })).toBeInTheDocument();
  });

  it('clicking a duration option calls onChange with a future ISO timestamp', async () => {
    const onChange = vi.fn();
    render(<MuteButton mutedUntil={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /^mute$/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /7 days/i }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0]![0];
    expect(typeof arg).toBe('string');
    expect(new Date(arg).getTime()).toBeGreaterThan(Date.now());
  });

  it('clicking "Forever" calls onChange with the sentinel', async () => {
    const onChange = vi.fn();
    render(<MuteButton mutedUntil={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /^mute$/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /forever/i }));
    expect(onChange).toHaveBeenCalledWith(FOREVER_SENTINEL);
  });

  it('clicking "Unmute" calls onChange with null', async () => {
    const onChange = vi.fn();
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    render(<MuteButton mutedUntil={future} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /muted until/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /unmute/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
