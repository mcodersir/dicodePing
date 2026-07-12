from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', 'build', 'dist', 'out', '.gradle', '.idea', '__pycache__', 'node_modules'}
errors = []
warnings = []

for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in EXCLUDED for part in path.parts):
        continue
    rel = path.relative_to(ROOT).as_posix()
    if path.suffix.lower() in {'.jks', '.keystore', '.p12', '.pfx', '.pem', '.key'}:
        errors.append(f'private key/signing material must not be committed: {rel}')
    if path.suffix.lower() in {'.py', '.kt', '.java', '.xml', '.json', '.gradle', '.kts'}:
        text = path.read_text('utf-8', errors='ignore')
        if re.search(r'\bverify\s*=\s*False\b', text):
            errors.append(f'TLS verification disabled: {rel}')
        if re.search(r'(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9_\-]{20,}', text):
            warnings.append(f'possible embedded credential: {rel}')

vpn_files = []
for path in ROOT.rglob('*.kt'):
    if any(part in EXCLUDED for part in path.parts):
        continue
    text = path.read_text('utf-8', errors='ignore')
    if 'VpnService' in text and 'addRoute' in text:
        vpn_files.append(path)
if vpn_files and not any(re.search(r'\.addRoute\(\s*"::"\s*,\s*0\s*\)', p.read_text('utf-8', errors='ignore')) for p in vpn_files):
    errors.append('Android VpnService has no IPv6 default route (::/0); IPv6 may bypass the tunnel')

# Native runtime/build artifacts must be fetched and verified by the build
# workflows, not committed as opaque source files.
if (ROOT / '.git').exists():
    try:
        tracked = {
            row.strip()
            for row in subprocess.check_output(
                ['git', '-C', str(ROOT), 'ls-files'], text=True, encoding='utf-8'
            ).splitlines()
            if row.strip()
        }
        forbidden_exact = {
            'core/xray.exe',
            'core/xray',
            'core/wintun.dll',
            'core/geoip.dat',
            'core/geosite.dat',
        }
        forbidden = sorted((tracked & forbidden_exact) | {row for row in tracked if row.lower().endswith('.aar')})
        for rel in forbidden:
            errors.append(f'opaque native artifact must not be committed: {rel}')
    except (OSError, subprocess.SubprocessError):
        warnings.append('git index was unavailable; tracked native-artifact policy was not evaluated')

result = {'errors': errors, 'warnings': warnings}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
