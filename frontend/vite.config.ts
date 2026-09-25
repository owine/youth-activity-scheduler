import { defineConfig } from 'vite';
import { TanStackRouterVite } from '@tanstack/router-vite-plugin';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { sentryVitePlugin } from '@sentry/vite-plugin';
import path from 'node:path';

// Source-map upload to GlitchTip. Only the auth token is secret (a buildkit
// secret in the Dockerfile, never a build arg); URL, org and project are plain
// build args. Without a token the plugin is fully disabled and leaves the build
// output untouched (no debug IDs injected, maps kept as before).
const sentryAuthToken = process.env.SENTRY_AUTH_TOKEN || undefined;

export default defineConfig({
  plugins: [
    TanStackRouterVite(),
    tailwindcss(),
    react(),
    // Must come after the other plugins so it sees final chunks.
    sentryVitePlugin({
      disable: !sentryAuthToken,
      authToken: sentryAuthToken,
      url: process.env.SENTRY_URL,
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      // Plugin telemetry would go to sentry.io, not GlitchTip.
      telemetry: false,
      // Maps are matched by debug ID (GlitchTip 6 supports artifact bundles),
      // so no release needs creating here. The runtime release comes from the
      // <meta> the backend renders, which keeps this build independent of the
      // commit SHA and its Docker layer cacheable across commits.
      release: { create: false, finalize: false, inject: false },
      sourcemaps: {
        // Uploaded, so no reason to also serve them publicly from /assets.
        filesToDeleteAfterUpload: ['./dist/**/*.map'],
      },
      // A GlitchTip outage must not block publishing the image.
      errorHandler: (err) => {
        console.warn('[sentry] source map upload failed; continuing build:', err);
      },
    }),
  ],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8080', changeOrigin: true },
      '/readyz': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    // 'hidden' when uploading: the maps are deleted after upload, so a
    // sourceMappingURL comment would only point browsers at a 404.
    sourcemap: sentryAuthToken ? 'hidden' : true,
  },
});
