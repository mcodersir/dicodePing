"""Canonical APK containers; application payload and signing identity stay unchanged."""
import concurrent.futures,hashlib,json,os,pathlib,re,shutil,subprocess,urllib.request,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1];PIN={'certificate_sha256':'0a483317ee0bd0e2aea48d2be72c30f206d3cceb3f178ea18ca22a17d6cdfcc0'}
INPUT=ROOT/'canonical-apk-input';OUT=ROOT/'dist-android';TOOLS=pathlib.Path(os.environ['ANDROID_HOME'])/'build-tools/37.0.0'
SIG=re.compile(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))$',re.I)
def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def rebuild(item):
 name,expected=item;original=INPUT/name
 assert sha(original)==expected,'Published input changed'
 unsigned=INPUT/(name+'.unsigned');aligned=INPUT/(name+'.aligned');target=OUT/name
 with zipfile.ZipFile(original) as before,zipfile.ZipFile(unsigned,'w',allowZip64=False) as after:
  assert before.testzip() is None
  entries=[i for i in before.infolist() if not i.is_dir() and not SIG.fullmatch(i.filename)]
  assert len(entries)==len({i.filename for i in entries})
  entries.sort(key=lambda i:(0 if i.filename=='AndroidManifest.xml' else 1 if i.filename=='resources.arsc' else 2,i.filename))
  for old in entries:
   new=zipfile.ZipInfo(old.filename,(1980,1,1,0,0,0));new.create_system=0;new.external_attr=0x20
   new.compress_type=zipfile.ZIP_STORED if old.filename in ('AndroidManifest.xml','resources.arsc') else old.compress_type
   with before.open(old) as input,after.open(new,'w') as output:shutil.copyfileobj(input,output,1024*1024)
 subprocess.run([str(TOOLS/'zipalign'),'-f','-P','16','4',str(unsigned),str(aligned)],check=True)
 subprocess.run([str(TOOLS/'apksigner'),'sign','--ks',os.environ['DICODE_KEYSTORE_PATH'],'--ks-pass','env:DICODE_KEYSTORE_PASSWORD','--ks-key-alias',os.environ['DICODE_KEY_ALIAS'],'--key-pass','env:DICODE_KEY_PASSWORD','--v1-signing-enabled','true','--v2-signing-enabled','true','--v3-signing-enabled','true','--v4-signing-enabled','false','--out',str(target),str(aligned)],check=True)
 verify=subprocess.run([str(TOOLS/'apksigner'),'verify','--min-sdk-version','21','--verbose','--print-certs',str(target)],check=True,capture_output=True,text=True).stdout
 for scheme in [1,2,3]:assert re.search(rf'Verified using v{scheme} scheme .*: true',verify)
 assert PIN['certificate_sha256'] in verify
 subprocess.run([str(TOOLS/'zipalign'),'-c','-P','16','4',str(target)],check=True)
 with zipfile.ZipFile(original) as before,zipfile.ZipFile(target) as after:
  names={i.filename for i in before.infolist() if not i.is_dir() and not SIG.fullmatch(i.filename)}
  assert names=={i.filename for i in after.infolist() if not i.is_dir() and not SIG.fullmatch(i.filename)}
  for n in names:assert hashlib.sha256(before.read(n)).digest()==hashlib.sha256(after.read(n)).digest(),n
  assert after.infolist()[0].filename=='AndroidManifest.xml'
  assert after.getinfo('AndroidManifest.xml').compress_type==0 and after.getinfo('resources.arsc').compress_type==0
 badging=subprocess.run([str(TOOLS/'aapt2'),'dump','badging',str(target)],check=True,capture_output=True,text=True).stdout
 assert "versionName='5.0.1'" in badging and "versionCode='55000100'" in badging
 print('PASS canonical ZIP, identical application payload, same signing key and V1/V2/V3:',name,flush=True)
 unsigned.unlink();aligned.unlink()
 return {'name':name,'original_sha256':expected,'sha256':sha(target),'size':target.stat().st_size}
def main():
 INPUT.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
 inputs={}
 for file in sorted(OUT.glob('*.apk')):
  inputs[file.name]=sha(file)
  shutil.copy2(file,INPUT/file.name)
 assert len(inputs)==6,'Expected all six final signed APKs'
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(rebuild,inputs.items()))
 (OUT/'SHA256SUMS-android.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in sorted(records,key=lambda r:r['name'])))
if __name__=='__main__':main()
