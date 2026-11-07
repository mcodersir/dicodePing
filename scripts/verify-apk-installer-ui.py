"""Install via a granting content provider and the native PackageInstaller UI."""
import argparse,hashlib,json,pathlib,re,subprocess,time,xml.etree.ElementTree as ET
p=argparse.ArgumentParser();p.add_argument('--abi',required=True);args=p.parse_args()
ROOT=pathlib.Path('installer-ui-evidence');ROOT.mkdir(exist_ok=True)
PACKAGE='ir.dicode.ping.fdroid';PROBE='ir.dicode.installprobe';records=[]
def adb(*parts,check=True,stdin=None):
 r=subprocess.run(['adb',*parts],stdin=stdin,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
 if check and r.returncode:raise RuntimeError(r.stdout.decode(errors='replace'))
 return r.stdout.decode(errors='replace')
def installed_hash():
 path=adb('shell','pm','path',PACKAGE,check=False).strip()
 if not path.startswith('package:'):return None
 return adb('shell','sha256sum',path.splitlines()[0][8:]).split()[0]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def allow_installer_source():
 adb('shell','am','start','-W','-a','android.settings.MANAGE_UNKNOWN_APP_SOURCES','-d','package:'+PROBE)
 last=''
 for attempt in range(15):
  adb('shell','uiautomator','dump','/sdcard/install-source.xml',check=False)
  last=adb('shell','cat','/sdcard/install-source.xml',check=False)
  try:
   for node in ET.fromstring(last).iter('node'):
    attrs=node.attrib
    if 'Switch' not in attrs.get('class','') and 'switch_widget' not in attrs.get('resource-id',''):continue
    if attrs.get('checked')=='true':
     adb('shell','input','keyevent','KEYCODE_BACK');time.sleep(1);return
    if attrs.get('enabled')=='true':
     bounds=re.findall(r'\d+',attrs.get('bounds',''))
     if len(bounds)==4:
      x1,y1,x2,y2=map(int,bounds);adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2));break
  except ET.ParseError:pass
  time.sleep(1)
 (ROOT/'install-source-permission.xml').write_text(last)
 raise RuntimeError('Native Settings did not allow the isolated installer source')
def install_ui(path,label):
 allow_installer_source()
 expected=sha(path)
 adb('shell','run-as',PROBE,'rm','-f','files/result.txt')
 with path.open('rb') as input:adb('shell','run-as',PROBE,'sh','-c',"'mkdir -p files && cat > files/package.apk'",stdin=input)
 adb('shell','am','force-stop',PROBE)
 adb('shell','am','start','-W','-f','0x10008000','-n',PROBE+'/.Launcher')
 last=''
 for attempt in range(35):
  result=adb('shell','run-as',PROBE,'cat','files/result.txt',check=False).strip()
  if installed_hash()==expected and result=='-1':
   time.sleep(1)
   records.append({'scenario':label,'success':True,'sha256':expected,'installer_result':result});return True
  adb('shell','uiautomator','dump','/sdcard/install-probe.xml',check=False)
  last=adb('shell','cat','/sdcard/install-probe.xml',check=False)
  try:
   for node in ET.fromstring(last).iter('node'):
    text=node.attrib.get('text','').strip().lower()
    if text in {'install','update','install anyway','continue','ok'} and node.attrib.get('enabled')=='true':
     bounds=re.findall(r'\d+',node.attrib.get('bounds',''))
     if len(bounds)==4:
      x1,y1,x2,y2=map(int,bounds);adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2));break
  except ET.ParseError:pass
  if 'problem parsing' in last.lower() or 'package appears to be invalid' in last.lower():break
  time.sleep(1)
 (ROOT/(label+'.xml')).write_text(last)
 records.append({'scenario':label,'success':False,'sha256':expected});return False
try:
 adb('install','-r','install-probe-build/probe.apk')
 adb('shell','appops','set',PROBE,'REQUEST_INSTALL_PACKAGES','allow')
 adb('shell','input','keyevent','KEYCODE_WAKEUP');adb('shell','wm','dismiss-keyguard',check=False)
 old=pathlib.Path('install-input991')/('DicodePing-4.9.991-'+args.abi+'.apk')
 new=pathlib.Path('dist-android')/old.name
 adb('uninstall',PACKAGE,check=False)
 before=install_ui(old,'original-fresh')
 print('Original public APK through native installer:',before,flush=True)
 adb('uninstall',PACKAGE,check=False)
 assert install_ui(new,'repacked-fresh'),'Repacked APK failed native PackageInstaller'
 assert 'Status: ok' in adb('shell','am','start','-W','-n',PACKAGE+'/com.v2ray.ang.ui.main.MainActivity')
 time.sleep(3);assert adb('shell','pidof',PACKAGE).strip()
 adb('uninstall',PACKAGE)
 adb('install','--no-streaming',str(old))
 assert install_ui(new,'repacked-update'),'Repacked APK failed native update flow'
 assert installed_hash()==sha(new)
 print('PASS native PackageInstaller: fresh install, actual installed bytes, launch and update',flush=True)
finally:
 (ROOT/'results.json').write_text(json.dumps(records,indent=2)+'\n')
 (ROOT/'logcat.txt').write_text(adb('logcat','-d',check=False))
