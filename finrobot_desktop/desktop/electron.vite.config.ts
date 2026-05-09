import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/main',
      rollupOptions: {
        input: { index: resolve(__dirname, 'electron/main.ts') },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/preload',
      rollupOptions: {
        input: { index: resolve(__dirname, 'electron/preload.ts') },
      },
    },
  },
  renderer: {
    plugins: [react(), tailwindcss()],
    root: resolve(__dirname, '.'),
    server: {
      proxy: {
        '/api': 'http://127.0.0.1:8321',
        '/health': 'http://127.0.0.1:8321',
        '/openapi.json': 'http://127.0.0.1:8321',
      },
    },
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: resolve(__dirname, 'index.html'),
      },
    },
  },
})
