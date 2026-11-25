import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const isStatic = process.env.VITE_STATIC === 'true';
/** Custom domain (chemmaps.de) and local static preview use `/`. */
const base = process.env.VITE_BASE ?? '/';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: isStatic
      ? undefined
      : {
          // Browser calls /api → backend :8000 (avoids CORS / host mismatch)
          '/api': {
            target: 'http://127.0.0.1:8000',
            changeOrigin: true,
            rewrite: (path) => path.replace(/^\/api/, '')
          }
        }
  },
  optimizeDeps: {
    include: ['deepscatter']
  },
  build: {
    commonjsOptions: {
      transformMixedEsModules: true
    }
  }
});
