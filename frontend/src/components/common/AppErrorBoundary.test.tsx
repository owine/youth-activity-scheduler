import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppErrorBoundary } from './AppErrorBoundary';

function Thrower(): never {
  throw new Error('render exploded');
}

describe('AppErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <AppErrorBoundary>
        <p>all good</p>
      </AppErrorBoundary>,
    );
    expect(screen.getByText('all good')).toBeInTheDocument();
  });

  it('renders a fallback with a reload action instead of a blank page', () => {
    // React logs caught render errors to console.error; keep the output clean.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      render(
        <AppErrorBoundary>
          <Thrower />
        </AppErrorBoundary>,
      );
    } finally {
      spy.mockRestore();
    }

    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong/i);
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument();
    expect(screen.queryByText('render exploded')).not.toBeInTheDocument();
  });
});
