import { defineConfig } from 'vite';
import { localApi } from './server.mjs';

const port = Number(process.env.SPARKIE_WEB_PORT || 5178);
export default defineConfig({
  plugins: [localApi(port)],
  server: { host: '127.0.0.1', port, strictPort: true, open: false },
});
