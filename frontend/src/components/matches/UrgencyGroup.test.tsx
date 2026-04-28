import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { UrgencyGroup } from './UrgencyGroup';

const m = {
  kid_id: 1,
  offering_id: 1,
  score: 0.9,
  reasons: {},
  computed_at: '2026-04-24T12:00:00Z',
  offering: {
    id: 1,
    site_id: 1,
    site_name: 'X',
    name: 'T-Ball',
    program_type: 'other',
    age_min: null,
    age_max: null,
    start_date: null,
    end_date: null,
    days_of_week: [],
    time_start: null,
    time_end: null,
    price_cents: null,
    registration_url: null,
    registration_opens_at: null,
  },
};

describe('UrgencyGroup', () => {
  it('renders nothing when matches is empty', () => {
    const { container } = render(<UrgencyGroup title="t" matches={[]} onSelect={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
  it('renders a card per match', () => {
    render(<UrgencyGroup title="t" matches={[m as never]} onSelect={() => {}} />);
    expect(screen.getByText('T-Ball')).toBeInTheDocument();
  });
});
