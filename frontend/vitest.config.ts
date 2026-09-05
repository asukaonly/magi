import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    // Translation checker tests run with node:test through check:i18n.
    include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}', 'scripts/check-boundaries.test.mjs'],
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
});
