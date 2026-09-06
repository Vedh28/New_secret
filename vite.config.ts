import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  optimizeDeps: { exclude: ["maplibre-gl"] },
  build: { outDir: "dist", emptyOutDir: true }
});
