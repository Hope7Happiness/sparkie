import { defineConfig } from 'vite';
import { localApi } from './server.mjs';
import { multitrackApi } from './multitrack-server.mjs';
import frontendHelper from '@frontend-helper/vite';

const port = Number(process.env.SPARKIE_WEB_PORT || 5178);
export default defineConfig({
  plugins: [localApi(port), multitrackApi(port), frontendHelper({ initiallyOpen: false })],
  build: { rollupOptions: { input: ['index.html', 'multitrack.html'] } },
  server: { host: '0.0.0.0', port, strictPort: true, open: false },
});
