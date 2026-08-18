import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: path.resolve(__dirname, '../web'),
    emptyOutDir: false,
    // The build writes into ../web, which ALSO holds the hand-written vanilla
    // dashboard (web/index.html). Vite names its HTML output after the entry
    // file, so the entry is react.html — never index.html. Renaming it back
    // would silently overwrite the working dashboard on the next build.
    rollupOptions: {
      input: path.resolve(__dirname, 'react.html'),
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]'
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8600',
        changeOrigin: true,
      }
    }
  }
});
