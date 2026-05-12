import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const devServerHost = process.env.VITE_DEV_SERVER_HOST || '127.0.0.1'
const devServerPort = Number(process.env.VITE_DEV_SERVER_PORT || 5173)

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: devServerHost,
    port: devServerPort,
    strictPort: true,
    hmr: {
      host: devServerHost,
      port: devServerPort,
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
