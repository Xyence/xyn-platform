import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.indexOf(".css") >= 0) return undefined;
          if (id.indexOf("/src/app/pages/Artifact") >= 0 || id.indexOf("/src/app/components/artifacts/") >= 0) return "artifact-pages";
          if (id.indexOf("/src/app/pages/Draft") >= 0 || id.indexOf("/src/app/drafts/") >= 0) return "draft-pages";
          if (id.indexOf("/src/app/pages/") >= 0) return "page-misc";
          if (id.indexOf("node_modules") < 0) return undefined;
          if (
            id.indexOf("/react/") >= 0 ||
            id.indexOf("/react-dom/") >= 0 ||
            id.indexOf("/scheduler/") >= 0 ||
            id.indexOf("/react-router") >= 0 ||
            id.indexOf("/@remix-run/") >= 0 ||
            id.indexOf("/flexlayout-react/") >= 0 ||
            id.indexOf("/@xyflow/") >= 0 ||
            id.indexOf("/@tanstack/") >= 0
          ) {
            return "framework-vendor";
          }
          if (id.indexOf("/@tiptap/") >= 0 || id.indexOf("/marked/") >= 0 || id.indexOf("/turndown") >= 0 || id.indexOf("/dompurify/") >= 0) return "editor-vendor";
          if (id.indexOf("/mermaid/") >= 0) return "diagram-vendor";
          if (id.indexOf("/lucide-react/") >= 0) return "icons-vendor";
          return "misc-vendor";
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
