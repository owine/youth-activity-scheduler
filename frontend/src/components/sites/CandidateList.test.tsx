import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CandidateList } from './CandidateList';
import type { Candidate } from '@/lib/types';

const make = (overrides: Partial<Candidate>): Candidate => ({
  url: 'https://example.com/p',
  title: 'Page',
  kind: 'html',
  score: 0.5,
  reason: 'reason',
  ...overrides,
});

describe('CandidateList', () => {
  it('sorts candidates by score descending across high+low sections after disclosure expand', async () => {
    const cands = [
      make({ url: 'https://a', score: 0.5, title: 'A' }),
      make({ url: 'https://b', score: 0.9, title: 'B' }),
      make({ url: 'https://c', score: 0.3, title: 'C' }),
      make({ url: 'https://d', score: 0.85, title: 'D' }),
    ];
    render(<CandidateList candidates={cands} selectedUrls={new Set()} onChange={vi.fn()} />);
    // Initially only high-confidence (>=0.7) visible: B (0.9), D (0.85). Sorted desc.
    const visibleHigh = screen.getAllByRole('checkbox').map((cb) => cb.id.replace('cand-', ''));
    expect(visibleHigh).toEqual(['https://b', 'https://d']);
    // Expand disclosure
    await userEvent.click(screen.getByRole('button', { name: /show 2 more/i }));
    const allTitles = screen.getAllByRole('checkbox').map((cb) => cb.id.replace('cand-', ''));
    // After expand: low section appended (A 0.5, then C 0.3 — sorted desc within low)
    expect(allTitles).toEqual(['https://b', 'https://d', 'https://a', 'https://c']);
  });

  it('auto-checks candidates with score >= 0.7 and shows their reason', () => {
    const cands = [
      make({ url: 'https://hi', score: 0.85, title: 'Hi', reason: 'because' }),
      make({ url: 'https://lo', score: 0.4, title: 'Lo' }),
    ];
    const onChange = vi.fn();
    const { rerender } = render(
      <CandidateList
        candidates={cands}
        selectedUrls={new Set(['https://hi'])}
        onChange={onChange}
      />,
    );
    const hi = screen.getByLabelText(/Hi/);
    expect(hi).toBeChecked();
    expect(screen.getByText(/because/i)).toBeInTheDocument();
    rerender(
      <CandidateList
        candidates={cands}
        selectedUrls={new Set(['https://hi'])}
        onChange={onChange}
      />,
    );
  });

  it('collapses score < 0.7 candidates under a disclosure', async () => {
    const cands = [
      make({ url: 'https://hi', score: 0.85, title: 'Hi' }),
      make({ url: 'https://lo', score: 0.4, title: 'Lo' }),
    ];
    render(
      <CandidateList
        candidates={cands}
        selectedUrls={new Set(['https://hi'])}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/Lo/)).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /show 1 more/i }));
    expect(screen.getByLabelText(/Lo/)).toBeInTheDocument();
  });

  it('toggling a checkbox calls onChange with the updated Set', async () => {
    const cands = [make({ url: 'https://hi', score: 0.85, title: 'Hi' })];
    const onChange = vi.fn();
    render(
      <CandidateList
        candidates={cands}
        selectedUrls={new Set(['https://hi'])}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText(/Hi/));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]?.[0] as Set<string>;
    expect(next.has('https://hi')).toBe(false);
  });

  it('filters out PDF candidates entirely', () => {
    const cands = [
      make({ url: 'https://pdf', score: 0.9, title: 'PDF doc', kind: 'pdf' }),
      make({ url: 'https://html', score: 0.9, title: 'HTML page', kind: 'html' }),
    ];
    render(
      <CandidateList
        candidates={cands}
        selectedUrls={new Set(['https://html'])}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText(/PDF doc/)).toBeNull();
    expect(screen.getByText(/HTML page/)).toBeInTheDocument();
  });
});
