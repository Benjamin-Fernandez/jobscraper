// Vite builds the SPA straight into the Python package, so `python -m jobscraper
// web` can serve it from a clean checkout with no node toolchain present
// (PRD M10-T3). The built files under src/jobscraper/web/static/ are committed.
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const OUT_DIR = fileURLToPath(new URL('../src/jobscraper/web/static', import.meta.url))

export default defineConfig({
  plugins: [vue()],
  // Relative asset URLs: nothing in the bundle assumes it is served from `/`
  // on localhost (PRD 8.6 - no hardcoded host, API base is relative).
  base: './',
  build: {
    outDir: OUT_DIR,
    // The out dir is outside web/, so Vite will not clear it unless told to.
    // Without this, every build leaves the previous build's hashed files behind.
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` hot-reloads the UI while `python -m jobscraper web`
    // answers the API on its configured port.
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
  },
})
