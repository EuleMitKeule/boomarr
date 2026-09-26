import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

// The build is served by the Python backend from boomarr/web/dist. Relative
// asset URLs plus the <base> tag the server injects make it work under any
// server.url_base.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  build: {
    outDir: "../boomarr/web/dist",
    emptyOutDir: true,
    // Keep every asset a file: the CSP does not allow data: fonts/images.
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 800,
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:9797", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
