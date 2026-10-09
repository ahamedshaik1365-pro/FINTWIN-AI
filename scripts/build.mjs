import { cp, mkdir, copyFile } from 'node:fs/promises';

await mkdir('dist', { recursive: true });
await copyFile('index.html', 'dist/index.html');
await cp('src', 'dist/src', { recursive: true, force: true });
await cp('public', 'dist/public', { recursive: true, force: true });
console.log('Static FinTwin AI site built in dist/.');
