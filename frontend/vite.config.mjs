import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { localApi } from './server.mjs';
import { multitrackApi } from './multitrack-server.mjs';

const port = Number(process.env.SPARKIE_WEB_PORT || 5178);
const env = loadEnv('', fileURLToPath(new URL('../', import.meta.url)), 'SPARKIE_');
const workspaceServer = process.env.SPARKIE_WORKSPACE_SERVER || env.SPARKIE_WORKSPACE_SERVER || '127.0.0.1:8790';
export default defineConfig({
  plugins: [localApi(port), multitrackApi(port)],
  build: { rollupOptions: { input: ['index.html', 'multitrack.html', 'workspace.html'] } },
  server: { host: '0.0.0.0', port, strictPort: true, open: false,
    proxy: { '/workspace-api': { target: `http://${workspaceServer}`, ws: true,
      rewrite: path => path.replace(/^\/workspace-api/, '') } }
  },
});
