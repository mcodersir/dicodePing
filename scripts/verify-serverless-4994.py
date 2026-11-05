"""Check the pinned upstream Serverless feed with the exact packaged Xray."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=pathlib.Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
url = 'https://raw.githubusercontent.com/patterniha/Serverless-for-Iran/46468c76596e307263006f47ebc4b7a1c1413ce0/Subscription/Serverless-for-Iran.json'
with urllib.request.urlopen(url, timeout=30) as response:
    data = response.read()
assert hashlib.sha256(data).hexdigest() == '5345aef63f61e368ccb3a908f96325a1b545b7f1f1562f6707e74fdc691b6442'
binary = root / 'bin' / 'xray' / ('xray.exe' if os.name == 'nt' else 'xray')
env = {**os.environ, 'XRAY_LOCATION_ASSET': str(root / 'bin')}
with tempfile.TemporaryDirectory() as temporary:
    config = pathlib.Path(temporary) / 'serverless.json'
    for profile in json.loads(data):
        config.write_text(json.dumps(profile), encoding='utf-8')
        subprocess.run([str(binary), 'run', '-test', '-c', str(config)], env=env, check=True, timeout=30)
        print('Packaged Xray accepts', profile['remarks'], flush=True)
