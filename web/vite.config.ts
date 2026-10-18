/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Ports are off the common defaults on purpose: 47822 dev server, 47821 API.
const api = process.env.SEEN_API ?? "http://127.0.0.1:47821";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: process.env.SEEN_DEV_HOST ?? "127.0.0.1",
    port: 47822,
    strictPort: true,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  preview: { port: 47822, strictPort: true },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
