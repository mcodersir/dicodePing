import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import test from 'node:test';

test('desktop renderer references only controls present in the redesigned shell', async () => {
  const [html, script] = await Promise.all([
    readFile('src/ui/index.html', 'utf8'),
    readFile('src/ui/app.mjs', 'utf8'),
  ]);
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  const referencedIds = new Set([...script.matchAll(/\$\('#([A-Za-z0-9_-]+)/g)].map(match => match[1]));
  assert.deepEqual([...referencedIds].filter(id => !ids.has(id)), []);
  assert.match(html, /id="auto-connect"/);
  assert.match(html, /id="source-tabs"/);
});

test('the supplied brand and Vazirmatn assets are bundled for every UI', async () => {
  const css = await readFile('src/ui/app.css', 'utf8');
  assert.match(css, /font-family:Vazirmatn/);
  await Promise.all([
    access('assets/app.ico'),
    access('assets/app.png'),
    access('src/ui/assets/app.svg'),
    access('src/ui/fonts/Vazirmatn-Regular.ttf'),
    access('apps/android/app/src/main/res/font/vazirmatn_regular.ttf'),
    access('apps/android/app/src/main/res/drawable/ic_dicode_logo.xml'),
  ]);
});
