import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import webfontDownload from 'vite-plugin-webfont-dl'
import path from 'path'

export default defineConfig({
  plugins: [react(), webfontDownload()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Proxy API routes to the hippomem backend during dev
    proxy: {
      '/chat': 'http://localhost:8719',
      '/messages': 'http://localhost:8719',
      '/memory': 'http://localhost:8719',
      '/traces': 'http://localhost:8719',
      '/stats': 'http://localhost:8719',
      '/health': 'http://localhost:8719',
    },
  },
})
