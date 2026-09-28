import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Default port avoids collision with FinRobot backend (8321)
export default defineConfig({
  // '/' for the desktop bundle. Set VITE_BASE_PATH (e.g. '/v2/') to emit asset
  // URLs for a build served from a sub-path; it also becomes import.meta.env
  // .BASE_URL, which the router uses as its basename.
  base: process.env.VITE_BASE_PATH ?? '/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // In dev, proxy API/chat/health to FinRobot FastAPI backend
      '/api': 'http://127.0.0.1:8321',
      '/chat': 'http://127.0.0.1:8321',
      '/health': 'http://127.0.0.1:8321',
      '/openapi.json': 'http://127.0.0.1:8321',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Realistic per-chunk budget. A few chunks legitimately exceed 600KB, but
    // every one of them is LAZY — none sit on the eager landing path, which
    // keeps the index entry chunk at ~280KB:
    //   - bundle-*.js (~1.6MB)  `src/export/bundle.ts`, a `?raw` STRING blob of
    //       the pre-built report viewer IIFE inlined verbatim into exported
    //       .html. A string, not splittable code; loaded only on export.
    //   - spline-viewer-*.js (~2.3MB) + physics-*.js (~2MB)  the @splinetool 3D
    //       viewer runtime, dynamically import()-ed by SplineHero ONLY when the
    //       hero actually mounts (tab visible + scrolled into view). Off cold
    //       start — a static import used to weld this onto index (2.4MB eager).
    // Everything on the eager path (vendors + index + route bundles) stays well
    // under this limit via the manualChunks split + lazy routes, so we leave the
    // warning ENABLED at 600KB to catch a real regression — i.e. something heavy
    // sneaking back onto the eager graph the way Spline used to.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Function form so we can also pull a vendor's transitive deps (e.g.
        // recharts' d3-* tree) into the same chunk, not just the top package.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const inPkg = (...pkgs: string[]) => pkgs.some((p) => id.includes(`node_modules/${p}/`))
          // recharts + its d3 dependency tree — the biggest vendor that's still
          // eager (charts render in the landing tables). Carved into its own
          // chunk so it caches independently and doesn't bloat the index entry.
          if (
            inPkg(
              'recharts',
              'd3-shape',
              'd3-scale',
              'd3-array',
              'd3-path',
              'd3-time',
              'd3-format',
              'd3-interpolate',
              'd3-color',
              'd3-time-format',
              'd3-ease',
              'd3-timer',
              'victory-vendor',
              'internmap',
              'decimal.js-light',
            )
          )
            return 'vendor-charts'
          if (inPkg('react-router-dom', 'react-router', 'react-dom', 'react')) return 'vendor-react'
          if (inPkg('@tanstack/react-query')) return 'vendor-query'
          if (inPkg('@ai-sdk/react', '@ai-sdk/ui-utils', 'ai')) return 'vendor-ai-sdk'
          if (inPkg('@lingui/core', '@lingui/react')) return 'vendor-i18n'
          if (inPkg('@tauri-apps/api', '@tauri-apps/plugin-')) return 'vendor-tauri'
          // Small app-wide utilities — grouped so they cache as one unit.
          if (inPkg('zustand', 'cmdk', 'use-debounce', 'openapi-fetch')) return 'vendor-utils'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/out/**',
      // Playwright e2e specs use @playwright/test, not vitest. Without this,
      // vitest crashes with "test.beforeEach() not expected here".
      '**/e2e/**',
    ],
  },
})
