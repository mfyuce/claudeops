import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
  // Tek kopya: iki `node_modules`tan React paketlenirse derleme geçer ama panel boş açılır (27 Kas).
  resolve: { dedupe: ["react", "react-dom", "scheduler"] },
  build: { sourcemap: true, outDir: "dist" },
})
