import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/status': 'http://localhost:8080',
      '/positions': 'http://localhost:8080',
      '/trades': 'http://localhost:8080',
      '/signals': 'http://localhost:8080',
      '/strategy': 'http://localhost:8080',
      '/account': 'http://localhost:8080',
      '/settings': 'http://localhost:8080',
      '/control': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
  },
})
