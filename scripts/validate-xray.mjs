import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { parseProfile } from '../src/core/profiles.mjs';
import { createClientConfig } from '../src/core/xray-config.mjs';

const binary = process.env.DICODE_XRAY || (process.platform === 'win32' ? 'xray.exe' : 'xray');
const samples = [
  'vless://11111111-1111-4111-8111-111111111111@example.com:443?security=reality&type=tcp&sni=cdn.example.com&fp=chrome&pbk=p5_gcvGalb9xZikaKYzTy_Reo5k3vqY-A_P3qQbthHE&sid=aa#reality',
  'trojan://secret@example.com:443?security=tls&type=ws&host=cdn.example.com&path=%2Fws&sni=cdn.example.com#trojan',
  'ss://YWVzLTEyOC1nY206c2VjcmV0@example.com:8388#ss'
];
const directory = await mkdtemp(path.join(os.tmpdir(), 'dicode-xray-validation-'));
try {
  for (let index = 0; index < samples.length; index += 1) {
    const file = path.join(directory, `${index}.json`);
    await writeFile(file, JSON.stringify(createClientConfig(parseProfile(samples[index]))));
    const result = spawnSync(binary, ['run', '-test', '-config', file], { encoding: 'utf8', windowsHide: true });
    if (result.status !== 0) throw new Error(`Xray rejected sample ${index}: ${result.stderr || result.stdout}`);
  }
  console.log(`Xray accepted ${samples.length} generated configurations`);
} finally {
  await rm(directory, { recursive: true, force: true });
}
