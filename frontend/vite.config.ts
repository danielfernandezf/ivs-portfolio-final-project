import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Sin host explicito Vite solo escucha en ::1 (IPv6) y el navegador,
    // que resuelve localhost a 127.0.0.1, recibe ERR_CONNECTION_REFUSED.
    host: true,
    // Puertos propios (3016/8011) para poder correr en paralelo con ivs-portfolio-v2,
    // que sigue usando 3015/8010.
    port: 3016,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8011',
        changeOrigin: true,
      },
    },
  },
})
