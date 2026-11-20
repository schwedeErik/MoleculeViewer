import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Browser calls /api → backend :8000 (avoids CORS / host mismatch)
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  optimizeDeps: {
    include: ['deepscatter'],
  },
  build: {
    commonjsOptions: {
      transformMixedEsModules: true,
    },
  },
});
