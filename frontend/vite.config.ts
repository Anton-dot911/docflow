import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Route backend calls through the dev server so the web app can use
    // same-origin paths; targets the FastAPI backend (uv run fastapi dev,
    // default port 8000).
    proxy: {
      "/health": "http://localhost:8000",
      "/api": "http://localhost:8000",
    },
  },
});
