import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // Keep DOM tests within the local Docker build's CPU/memory budget.
    maxWorkers: 2,
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
});
