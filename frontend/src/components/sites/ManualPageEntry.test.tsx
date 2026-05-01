import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ManualPageEntry, type ManualEntry } from './ManualPageEntry';

describe('ManualPageEntry', () => {
  it('adds a URL with selected kind to the list when Add is clicked', async () => {
    const onChange = vi.fn();
    render(<ManualPageEntry existingUrls={new Set()} value={[]} onChange={onChange} />);
    await userEvent.type(screen.getByLabelText(/manual url/i), 'https://example.com/reg');
    await userEvent.selectOptions(screen.getByLabelText(/manual kind/i), 'registration');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(onChange).toHaveBeenCalledWith([
      { url: 'https://example.com/reg', kind: 'registration' },
    ]);
  });

  it('removes an entry when × is clicked', async () => {
    const onChange = vi.fn();
    const initial: ManualEntry[] = [{ url: 'https://example.com/a', kind: 'schedule' }];
    render(<ManualPageEntry existingUrls={new Set()} value={initial} onChange={onChange} />);
    await userEvent.click(
      screen.getByRole('button', { name: /remove https:\/\/example\.com\/a/i }),
    );
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('rejects a URL that duplicates an existing candidate URL', async () => {
    const onChange = vi.fn();
    render(
      <ManualPageEntry
        existingUrls={new Set(['https://example.com/sched'])}
        value={[]}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByLabelText(/manual url/i), 'https://example.com/sched');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(screen.getByText(/already in list/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('rejects a URL that duplicates another manual entry', async () => {
    const onChange = vi.fn();
    const initial: ManualEntry[] = [{ url: 'https://example.com/a', kind: 'schedule' }];
    render(<ManualPageEntry existingUrls={new Set()} value={initial} onChange={onChange} />);
    await userEvent.type(screen.getByLabelText(/manual url/i), 'https://example.com/a');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(screen.getByText(/already in list/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
