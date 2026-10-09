import { resolve } from 'node:path';
process.env.FINTWIN_ROOT = resolve('dist');
await import('./server.mjs');
