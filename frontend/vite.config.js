import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Le front appelle /api ; Vite relaie vers Django. Évite toute
    // configuration CORS en développement.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
