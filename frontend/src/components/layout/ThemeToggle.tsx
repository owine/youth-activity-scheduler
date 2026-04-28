import { useEffect, useState } from 'react';
import { Moon, Sun, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { applyTheme, getStoredTheme, setStoredTheme, type Theme } from '@/lib/theme';

const order: Theme[] = ['system', 'light', 'dark'];
const Icon = { system: Monitor, light: Sun, dark: Moon } as const;
const label: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };

export function ThemeToggle() {
  const [t, setT] = useState<Theme>('system');

  useEffect(() => {
    setT(getStoredTheme());
  }, []);

  // React to OS-level changes when in system mode.
  useEffect(() => {
    if (t !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => applyTheme('system');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [t]);

  const cycle = () => {
    const next = order[(order.indexOf(t) + 1) % order.length]!;
    setStoredTheme(next);
    setT(next);
  };

  const C = Icon[t];
  return (
    <Button variant="ghost" size="sm" onClick={cycle} aria-label={`Theme: ${label[t]}`}>
      <C className="h-4 w-4" />
    </Button>
  );
}
