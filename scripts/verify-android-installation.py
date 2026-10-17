#!/usr/bin/env python3
"""Exercise the signed public release via Android PackageInstaller (no test/downgrade flags)."""
import pathlib,subprocess,json
root=pathlib.Path('install-check'); package='ir.dicode.ping.fdroid'; results=[]
def adb(*args):
    r=subprocess.run(['adb',*args],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=100)
    print('adb',' '.join(args),'exit',r.returncode,'\n'+r.stdout,flush=True)
    return r
try:
    adb('shell','getprop')
    for previous in [None,'4.8.0','4.9.1']:
        adb('uninstall',package)
        if previous:
            r=adb('install','--no-streaming',str(root/(previous+'.apk')))
            results.append({'scenario':'baseline '+previous,'success':r.returncode==0,'output':r.stdout})
        r=adb('install','--no-streaming','-r',str(root/'4.9.2.apk'))
        results.append({'scenario':'4.9.2 '+('fresh' if previous is None else 'upgrade from '+previous),'success':r.returncode==0,'output':r.stdout})
        if r.returncode==0:
            adb('shell','dumpsys','package',package)
            adb('shell','am','start','-W','-n',package+'/com.v2ray.ang.ui.main.MainActivity')
            adb('shell','am','force-stop',package)
finally:
    (root/'installation-results.json').write_text(json.dumps(results,indent=2))
    log=adb('logcat','-d');(root/'package-manager-logcat.txt').write_text(log.stdout)
assert results and all(r['success'] for r in results),'A signed release could not be installed; see installation-results.json'
print('PASS signed published APK: fresh installation and upgrades',flush=True)
