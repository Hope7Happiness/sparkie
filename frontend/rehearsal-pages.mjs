import { readFileSync } from 'node:fs';

// Keep rehearsal content in presentation/ while preserving existing page URLs.
const pages = new Map(['demo-script.html', 'demo-script-original.html'].map(name =>
  [name, new URL('../presentation/' + name, import.meta.url)]));

export function rehearsalPages() {
  return {
    name: 'sparkie-rehearsal-pages',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const name = new URL(req.url, 'http://localhost').pathname.slice(1);
        if (!pages.has(name)) return next();
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(readFileSync(pages.get(name)));
      });
    },
    generateBundle() {
      for (const [fileName, path] of pages) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(path) });
      }
    },
  };
}
