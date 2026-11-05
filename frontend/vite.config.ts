import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Django dev server
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    chunkSizeWarningLimit: 1100, // maplibre-gl is ~1 MB by itself
    rollupOptions: {
      output: {
        // vendor chunks change rarely, so browsers keep them cached across deploys
        manualChunks: { maplibre: ['maplibre-gl'], react: ['react', 'react-dom'] },
      },
    },
  },
  test: {
    environment: 'node',
  },
})
