import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Default port avoids collision with FinAgent backend (8321)
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // In dev, proxy API/chat/health to FinAgent FastAPI backend
      "/api": "http://127.0.0.1:8321",
      "/chat": "http://127.0.0.1:8321",
      "/health": "http://127.0.0.1:8321",
      "/openapi.json": "http://127.0.0.1:8321",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
    exclude: ["**/node_modules/**", "**/dist/**", "**/out/**"],
  },
});
