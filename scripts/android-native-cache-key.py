#!/usr/bin/env python3
"""Hash native Android inputs independently of desktop packaging and Kotlin UI edits."""
import hashlib,json,os,pathlib,re,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
LEGACY_INPUT_DIGEST='33dbd80308880e979af0cc54179045c7b28c7d90a2fd4e702a5853ff6624dbc7'
LEGACY_CACHE_KEY='Linux-dicode-native-v1-226ca5cde783783fb04014042f4dafa8d713ac07fb10ff59f3f073c9fee58d74'
PIN_FILE='scripts/runtime-pins-4.9.991.json'
WORKFLOWS=['.github/workflows/release.yml','.github/workflows/android-preflight.yml']

def source_files():
    return sorted(filter(None,subprocess.check_output(['git','ls-files','-z','--','scripts/stage-*.py','scripts/build-android-core.sh','scripts/singbox-android-pins.json','scripts/patches','apps/fox-helper'],cwd=ROOT).decode().split('\0')))

def inputs(read=None):
    read=read or (lambda name:(ROOT/name).read_bytes())
    pins=json.loads(read(PIN_FILE))
    # Mihomo is desktop-only. Every other pin remains part of the Android key.
    for key in list(pins):
        if key=='mihomo' or key.startswith('mihomo_'):del pins[key]
    files={name:hashlib.sha256(read(name)).hexdigest() for name in source_files()}
    recipes={}
    for name in WORKFLOWS:
        text=read(name).decode()
        start=re.search(r'(?m)^    - name: Build pinned hev TUN.*$',text)
        end=re.search(r'(?m)^    - name: Save verified Android native payloads.*$',text)
        if not start or not end or end.start()<=start.start():raise ValueError('Native build recipe is missing: '+name)
        recipes[name]={'native_steps':text[start.start():end.start()],
                       'toolchains':re.findall(r'(?m)^\s*(?:go-version|java-version):\s*(.+)$',text)}
    return {'pins':pins,'files':files,'recipes':recipes}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def cache_key(value,system='Linux'):
    fingerprint=digest(value)
    if system=='Linux' and fingerprint==LEGACY_INPUT_DIGEST:return LEGACY_CACHE_KEY
    return system+'-dicode-native-v2-'+fingerprint

if __name__=='__main__':print('key='+cache_key(inputs(),os.environ.get('RUNNER_OS','Linux')))
