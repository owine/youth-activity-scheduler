import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Date-only bugs (new Date('YYYY-MM-DD') is UTC midnight, toISOString() is the
// UTC date) are invisible in UTC, which is where CI runs. Default to a US zone
// so the regression tests exercise them; workers inherit this env. An explicit
// TZ still wins, e.g. `TZ=UTC pnpm run test`.
process.env.TZ ||= 'America/New_York';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  test: {
    environment: 'happy-dom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**'],
  },
});
