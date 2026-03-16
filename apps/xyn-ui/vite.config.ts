import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.indexOf(".css") >= 0) return undefined;
          if (id.indexOf("node_modules") < 0) return undefined;

          // Keep React/router/layout/runtime dependencies in Vite's default vendor graph.
          // Pulling them into separate manual chunks created circular imports that left
          // hook bindings undefined at runtime in production.
          if (id.indexOf("/prosemirror-") >= 0) return "prosemirror-vendor";
          if (id.indexOf("/@tiptap/") >= 0) return "tiptap-vendor";
          if (id.indexOf("/marked/") >= 0 || id.indexOf("/turndown") >= 0 || id.indexOf("/dompurify/") >= 0) return "markdown-vendor";
          if (id.indexOf("/mermaid/") >= 0) return "diagram-vendor";
          if (id.indexOf("/lucide-react/") >= 0) return "icons-vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: true,
    allowedHosts: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
