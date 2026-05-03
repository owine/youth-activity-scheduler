import type { ReactNode } from 'react';
import { Footer } from './Footer';
import { TopBar } from './TopBar';

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <TopBar />
      <main className="container max-w-5xl flex-1 py-6">{children}</main>
      <Footer />
    </div>
  );
}
