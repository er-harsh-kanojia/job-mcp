import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// `npm run dev:mock` runs Vite with --mode mock, which loads .env.mock (VITE_MOCK=1).
// __MOCK__ is a compile-time constant, so production builds drop the mock module entirely.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const mock = env.VITE_MOCK === '1' || env.VITE_MOCK === 'true';
  return {
    plugins: [react()],
    define: { __MOCK__: JSON.stringify(mock) },
    server: {
      port: 5173,
      strictPort: false,
      proxy: mock
        ? undefined
        : { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false } },
    },
    build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
  };
});
