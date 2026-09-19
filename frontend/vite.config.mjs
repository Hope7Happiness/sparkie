import { defineConfig } from 'vite';
import frontendHelper from '@frontend-helper/vite';
import { localApi } from './server.mjs';

export default defineConfig({
  plugins: [localApi(), frontendHelper({ initiallyOpen: false })],
  server: { host: '127.0.0.1', port: 5178, strictPort: true, open: false },
});
