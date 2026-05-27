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
    // Split vendor chunks so the main app bundle stays cacheable across releases.
    // Route-level lazy load (router.tsx) carves ArtifactDetailPage + SettingsPage
    // out of the initial chunk. The 12-chapter ArtifactDetailPage lands around
    // ~510KB on its own — bump the warning limit to 600KB so vite stops
    // flagging it on every build; further sub-chapter splits would add network
    // chatter without measurable benefit on a Tauri file:// load.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-ai-sdk': ['@ai-sdk/react', '@ai-sdk/ui-utils'],
          'vendor-i18n': ['@lingui/core', '@lingui/react'],
          'vendor-tauri': [
            '@tauri-apps/api',
            '@tauri-apps/plugin-dialog',
            '@tauri-apps/plugin-fs',
            '@tauri-apps/plugin-global-shortcut',
          ],
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
