import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173; the backend runs on 3001 (its standalone default).
// The API client hits the backend directly (CORS is enabled on the backend),
// mirroring how NayaFlow's renderer used window.EXPOSED.bgServerPort.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
