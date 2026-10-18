#!/usr/bin/env python3
"""Exercise the signed public release via Android PackageInstaller (no test/downgrade flags)."""
import argparse,pathlib,subprocess,json,time
parser=argparse.ArgumentParser()
parser.add_argument('--candidate',type=pathlib.Path)
parser.add_argument('--alternate',type=pathlib.Path)
parser.add_argument('--version', default='4.9.2')
parser.add_argument('--code', type=int, default=45920100)
parser.add_argument('--baselines', nargs='+', default=['4.8.0','4.9.0','4.9.1','4.9.2'])
args=parser.parse_args()
root=pathlib.Path('install-check'); package='ir.dicode.ping.fdroid'; results=[]
def adb(*args):
    r=subprocess.run(['adb',*args],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=100)
    print('adb',' '.join(args),'exit',r.returncode,'\n'+r.stdout,flush=True)
    return r
try:
    adb('shell','getprop')
    if args.candidate:
        assert args.candidate.is_file()
        adb('root'); adb('wait-for-device')
    for previous in [None]+args.baselines:
        adb('uninstall',package)
        marker='/data/user/0/'+package+'/files/upgrade-fixture'
        if previous:
            r=adb('install','--no-streaming',str(root/(previous+'.apk')))
            results.append({'scenario':'baseline '+previous,'success':r.returncode==0,'output':r.stdout})
            if args.candidate and r.returncode==0:
                adb('shell','am','start','-W','-n',package+'/com.v2ray.ang.ui.main.MainActivity')
                adb('shell','am','force-stop',package)
                r=adb('shell','sh','-c',f"'mkdir -p {marker.rsplit('/',1)[0]} && echo keep-my-data > {marker}'")
                assert r.returncode==0,'Cannot create upgrade preservation fixture'
        r=adb('install','--no-streaming','-r',str(args.candidate or root/'4.9.2.apk'))
        results.append({'scenario':args.version+' '+('fresh' if previous is None else 'upgrade from '+previous),'success':r.returncode==0,'output':r.stdout})
        if r.returncode==0:
            info=adb('shell','dumpsys','package',package)
            if args.candidate:
                assert f'versionCode={args.code} ' in info.stdout and f'versionName={args.version}' in info.stdout
                if previous:
                    assert 'keep-my-data' in adb('shell','cat',marker).stdout,'Upgrade lost existing app data'
            launch=adb('shell','am','start','-W','-n',package+'/com.v2ray.ang.ui.main.MainActivity')
            if args.candidate:
                assert launch.returncode==0 and 'Status: ok' in launch.stdout,'Release activity could not start'
                time.sleep(3)
                assert adb('shell','pidof',package).returncode==0,'Release crashed after launch'
            adb('shell','am','force-stop',package)
    if args.alternate:
        r=adb('install','--no-streaming','-r',str(args.alternate))
        results.append({'scenario':'switch APK architecture without downgrade','success':r.returncode==0,'output':r.stdout})
        assert r.returncode==0 and 'keep-my-data' in adb('shell','cat',marker).stdout
finally:
    (root/'installation-results.json').write_text(json.dumps(results,indent=2))
    log=subprocess.run(['adb','logcat','-d'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(root/'package-manager-logcat.txt').write_text(log.stdout)
assert results and all(r['success'] for r in results),'A signed release could not be installed; see installation-results.json'
print('PASS signed published APK: fresh installation and upgrades',flush=True)
