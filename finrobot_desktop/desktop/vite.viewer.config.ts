import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Builds the standalone report viewer (src/export/viewer.tsx) into a SINGLE
// self-contained IIFE — one viewer.js + one viewer.css with fonts inlined — that
// exportReport inlines into the exported .html. Run via `npm run build:viewer`
// before the main build (the app imports the output as ?raw). Output is
// gitignored (src/export/generated/).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // React reads process.env.NODE_ENV; pin it so the bundle is the production
  // build (smaller, no dev warnings) even though this is a secondary entry.
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: 'src/export/generated',
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    // Inline fonts/images into the single CSS/JS so the export is one file.
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    lib: {
      entry: 'src/export/viewer.tsx',
      formats: ['iife'],
      name: 'FinRobotReportViewer',
      fileName: () => 'viewer.js',
    },
    rollupOptions: {
      output: { inlineDynamicImports: true, assetFileNames: 'viewer.[ext]' },
    },
  },
})
