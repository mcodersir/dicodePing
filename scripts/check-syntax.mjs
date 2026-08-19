import { readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const roots = ['src/core', 'src/desktop', 'src/ui'];
const files = [];
for (const root of roots) {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (entry.isFile() && entry.name.endsWith('.mjs')) files.push(path.join(root, entry.name));
  }
}
for (const file of files) {
  const result = spawnSync(process.execPath, ['--check', file], { stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status || 1);
}
console.log(`syntax ok: ${files.length} modules`);
