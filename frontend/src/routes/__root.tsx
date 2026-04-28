import { Outlet, createRootRoute } from '@tanstack/react-router';

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-4 py-3">
        <h1 className="text-lg font-semibold">YAS</h1>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
    </div>
  );
}
