import { createServer } from 'node:http';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, resolve, sep } from 'node:path';

const root = resolve(process.env.FINTWIN_ROOT || process.cwd());
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json', '.jpeg': 'image/jpeg', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.csv': 'text/csv; charset=utf-8', '.md': 'text/markdown; charset=utf-8' };
createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const file = resolve(root, relative);
  if (!file.startsWith(root + sep) && file !== resolve(root, 'index.html')) { res.writeHead(403).end(); return; }
  if (!existsSync(file) || !statSync(file).isFile()) { res.writeHead(404).end('Not found'); return; }
  res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  createReadStream(file).pipe(res);
}).listen(Number(process.env.PORT || 5173), process.env.HOST || '127.0.0.1', () => console.log(`FinTwin AI ready on ${process.env.HOST || '127.0.0.1'}:${process.env.PORT || 5173}`));
