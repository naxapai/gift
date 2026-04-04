import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const proxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: (assetInfo) => {
          const name = assetInfo.name || 'asset'
          if (name.endsWith('.css')) return 'assets/[name]'
          return 'assets/[name]'
        },
      },
    },
  },
  server: {
    fs: {
      allow: [path.resolve(__dirname, '..')],
    },
    proxy: {
      '/v1': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/bridge': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
})
