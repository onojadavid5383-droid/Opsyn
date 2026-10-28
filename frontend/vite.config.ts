// ============================================================
// OPSYN VITE CONFIG — apps/frontend/vite.config.ts
// ============================================================

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

const zustandEsm = resolve(__dirname, 'node_modules/zustand/esm')

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: [
      // Map zustand and its sub-paths to ESM so rollup's CJS plugin never
      // tries to parse zustand's CJS files, which have an unparseable
      // nested-object `exports.default` entry in zustand v4.
      { find: /^zustand\/(.+)$/, replacement: `${zustandEsm}/$1.js` },
      { find: 'zustand', replacement: `${zustandEsm}/index.js` },

      // Project path aliases
      // NOTE: '@shared' must precede '@' -- vite matches prefixes in
      // array order, so '@' would otherwise swallow it.
      { find: '@shared', replacement: resolve(__dirname, './shared-types/index.ts') },
      { find: '@', replacement: resolve(__dirname, './src') },
      { find: '@api', replacement: resolve(__dirname, './src/api') },
      { find: '@components', replacement: resolve(__dirname, './src/components') },
      { find: '@hooks', replacement: resolve(__dirname, './src/hooks') },
      { find: '@pages', replacement: resolve(__dirname, './src/pages') },
      { find: '@store', replacement: resolve(__dirname, './src/store') },
      { find: '@types', replacement: resolve(__dirname, './src/types') },
      { find: '@utils', replacement: resolve(__dirname, './src/utils') },
      { find: '@assets', replacement: resolve(__dirname, './src/assets') },
    ],
  },

  server: {
    port: 5173,

    // Allow Cloudflare Quick Tunnel URLs
    allowedHosts: ['.trycloudflare.com'],

    proxy: {
      '/api': {
        // In Docker Compose, resolve the backend by its service name. Local
        // Vite runs keep the localhost default; compose can override it.
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
    chunkSizeWarningLimit: 800,
  },

  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
