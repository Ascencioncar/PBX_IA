import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" => assets relativos, para servirse desde FastAPI en cualquier ruta.
// El proxy solo aplica en `npm run dev` (en producción el API es el mismo origen).
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
