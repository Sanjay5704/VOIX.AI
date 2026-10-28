import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the browser talks to Vite only; /v1 and /docs are proxied to the API,
// so no CORS is involved. Production builds call VITE_API_BASE_URL directly.
const api = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: api, changeOrigin: true },
      "/docs": { target: api, changeOrigin: true },
      "/openapi.json": { target: api, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
