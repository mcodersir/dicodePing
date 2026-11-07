"""Replace only Android assets after installer UI and upgrade gates succeed."""
import hashlib,json,os,pathlib,shutil,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'dist-android';PIN=json.loads((ROOT/'scripts/android991-repack-pins.json').read_text());PROOF=json.loads((ROOT/'android991-repack-provenance.json').read_text());REPO='mcodersir/dicodePing'
def api(method,path,body=None):
 cmd=['gh','api','--method',method,'repos/'+REPO+'/'+path]
 if body is not None:cmd+=['--input','-']
 r=subprocess.run(cmd,input=json.dumps(body) if body is not None else None,text=True,capture_output=True,check=True)
 return json.loads(r.stdout) if r.stdout.strip() else None
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def metadata():
 r=api('GET','releases/tags/v4.9.991');assert r['id']==PIN['release_id'] and not r['draft'];return r,{a['name']:a for a in r['assets']}
release,old=metadata();assert len(old)==25
names=list(PIN['apk_sha256'])+['SHA256SUMS-android.txt'];untouched={n:a['digest'] for n,a in old.items() if n not in names}
for row in PROOF['packages']:
 assert old[row['name']]['digest']=='sha256:'+row['original_sha256']
 assert sha(OUT/row['name'])==row['sha256']
tag='v4.9.991-android.2';ref=subprocess.run(['gh','api','repos/'+REPO+'/git/ref/tags/'+tag],capture_output=True,text=True)
if ref.returncode==0:assert json.loads(ref.stdout)['object']['sha']==os.environ['GITHUB_SHA']
else:api('POST','git/refs',{'ref':'refs/tags/'+tag,'sha':os.environ['GITHUB_SHA']})
stage=ROOT/'release-stage';stage.mkdir(exist_ok=True);files={}
for name in names:
 temporary='android-r2-'+name;shutil.copyfile(OUT/name,stage/temporary)
 files[name]={'temporary':temporary,'digest':'sha256:'+sha(OUT/name),'old_id':old[name]['id']}
subprocess.run(['gh','release','upload','v4.9.991','--repo',REPO,'--clobber',*[str(stage/r['temporary']) for r in files.values()]],check=True)
_,uploaded=metadata()
for name,row in files.items():
 a=uploaded[row['temporary']];assert a['state']=='uploaded' and a['digest']==row['digest'];row['new_id']=a['id']
swapped=[]
try:
 for name,row in files.items():
  api('PATCH','releases/assets/'+str(row['old_id']),{'name':'android-r1-backup-'+name});swapped.append(name)
  api('PATCH','releases/assets/'+str(row['new_id']),{'name':name})
 _,current=metadata()
 for name,row in files.items():assert current[name]['id']==row['new_id'] and current[name]['digest']==row['digest']
 for name,digest in untouched.items():assert current[name]['digest']==digest
 note='<!-- android-packaging-revision-2 -->\n\n### 📱 بازنگری ۲ بستهٔ اندروید\n\nAPKها با ساختار ZIP استاندارد و مانیفست بدون فشرده‌سازی، با همان هسته، فایل‌های اجرایی، نسخه و کلید امضا بازبسته‌بندی شدند. امضاهای V1/V2/V3، نصب از رابط PackageInstaller، اجرای برنامه و ارتقا با حفظ داده‌ها بررسی شدند. فایل قبلی را دوباره استفاده نکنید؛ APK را از لینک جدید دوباره دانلود و روی نصب فعلی نصب کنید.\n\n[گزارش آزمون بسته‌ها](https://github.com/'+REPO+'/actions/runs/'+os.environ['GITHUB_RUN_ID']+') · [سورس بازبسته‌بندی](https://github.com/'+REPO+'/tree/'+tag+')\n\n---\n\n'
 assert '<!-- android-packaging-revision-2 -->' not in release['body']
 api('PATCH','releases/'+str(release['id']),{'body':note+release['body']})
except BaseException:
 for name in reversed(swapped):
  row=files[name];api('PATCH','releases/assets/'+str(row['new_id']),{'name':row['temporary']});api('PATCH','releases/assets/'+str(row['old_id']),{'name':name})
 raise
for name in swapped:api('DELETE','releases/assets/'+str(files[name]['old_id']))
_,current=metadata();assert len(current)==25
for name,row in files.items():assert current[name]['digest']==row['digest']
for name,digest in untouched.items():assert current[name]['digest']==digest
print('PASS Android revision 2 published; six APKs and checksums replaced; every desktop asset unchanged',flush=True)
