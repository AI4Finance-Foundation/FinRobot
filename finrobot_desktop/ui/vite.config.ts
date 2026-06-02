import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Default port avoids collision with FinRobot backend (8321)
export default defineConfig({
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
    // Realistic per-chunk budget. The only chunk that legitimately exceeds 600KB
    // is `src/export/bundle.ts` — a `?raw` STRING blob of the pre-built report
    // viewer IIFE (recharts + React, ~1.4MB minified) that gets inlined verbatim
    // into exported .html. It is a string, not splittable code, and is already a
    // lazy chunk loaded only on export. Everything else (vendors + route bundles)
    // is kept under this limit by the manualChunks split below, so we leave the
    // warning ENABLED at 600KB to catch real regressions; the one expected
    // over-budget chunk (bundle-*.js) is the inlined export viewer by design.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Function form so we can also pull a vendor's transitive deps (e.g.
        // recharts' d3-* tree) into the same chunk, not just the top package.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const inPkg = (...pkgs: string[]) => pkgs.some((p) => id.includes(`node_modules/${p}/`))
          // recharts + its d3 dependency tree — the single biggest vendor in the
          // app entry. Carving it out drops the eager index chunk well under 600KB.
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
