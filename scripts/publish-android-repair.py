#!/usr/bin/env python3
"""Stage verified APKs, swap release asset names, and retain rollback until verified."""
import hashlib,json,os,pathlib,shutil,subprocess

ROOT=pathlib.Path(__file__).resolve().parent.parent
PIN=json.loads((ROOT/'scripts/android-package-revision-2.json').read_text())
OUT=ROOT/'dist-install'
PROVENANCE=json.loads((OUT/'android-build2-provenance.json').read_text())
REPO=os.environ['GITHUB_REPOSITORY']
assert REPO=='mcodersir/dicodePing'
def api(method,path,body=None):
    cmd=['gh','api','--method',method,'repos/'+REPO+'/'+path]
    if body is not None:cmd+=['--input','-']
    r=subprocess.run(cmd,input=json.dumps(body) if body is not None else None,text=True,capture_output=True,check=True)
    return json.loads(r.stdout) if r.stdout.strip() else None
def metadata():
    r=api('GET','releases/tags/v4.9.2')
    assert not r['draft'] and not r['prerelease']
    return r,{a['name']:a for a in r['assets']}
release,old=metadata()
for row in PROVENANCE['packages']:
    assert old[row['name']]['digest']=='sha256:'+row['original_sha256'],'Original assets changed; refusing publication'
    assert row['version_code']==45920100
    assert hashlib.sha256((OUT/row['name']).read_bytes()).hexdigest()==row['sha256']
sha=os.environ['GITHUB_SHA']
tag='v4.9.2-android.2'
ref=subprocess.run(['gh','api','repos/'+REPO+'/git/ref/tags/'+tag],text=True,capture_output=True)
if ref.returncode==0:
    assert json.loads(ref.stdout)['object']['sha']==sha,'Refusing to replace an existing tag'
else:
    api('POST','git/refs',{'ref':'refs/tags/'+tag,'sha':sha})
stage=ROOT/'release-stage'
stage.mkdir(exist_ok=True)
files={}
for name in [r['name'] for r in PROVENANCE['packages']]+['SHA256SUMS-android.txt']:
    temporary='android-build2-'+name
    shutil.copyfile(OUT/name,stage/temporary)
    files[name]={'temporary':temporary,'digest':'sha256:'+hashlib.sha256((OUT/name).read_bytes()).hexdigest()}
subprocess.run(['gh','release','upload','v4.9.2','--repo',REPO,'--clobber',*[str(stage/x['temporary']) for x in files.values()]],check=True)
_,uploaded=metadata()
for name,record in files.items():
    asset=uploaded[record['temporary']]
    assert asset['digest']==record['digest'] and asset['state']=='uploaded' and asset['size']>0
    record['new_id']=asset['id'];record['old_id']=old[name]['id']
swapped=[]
try:
    for name,record in files.items():
        backup='android-build1-backup-'+name
        api('PATCH','releases/assets/'+str(record['old_id']),{'name':backup})
        swapped.append(name)
        api('PATCH','releases/assets/'+str(record['new_id']),{'name':name})
    _,current=metadata()
    for name,record in files.items():
        assert current[name]['id']==record['new_id'] and current[name]['digest']==record['digest']
    body=release['body']
    marker='<!-- android-install-build-2 -->'
    assert marker not in body,'This repair was already published'
    note=marker+'\n\n**بستهٔ اندروید بازنگری ۲ — همان نسخهٔ ۴.۹.۲**\n\n'
    note+='APKها با همان کد اجرایی، فایل‌های مسیریابی و کلید امضا، با کد داخلی بالاتر و یکسان 45920100 و امضای V1/V2/V3 بازبسته‌بندی شدند. تعویض Universal و ARM64 در این بازنگری کاهش نسخه محسوب نمی‌شود. آزمون نصب تازه، ارتقا از ۴.۸.۰، ۴.۹.۰، ۴.۹.۱ و خود ۴.۹.۲، حفظ داده و اجرای بستهٔ امضاشده پیش از جایگزینی انجام شد.\n\n'
    note+='[سورس بازبسته‌بندی و آزمون‌ها](https://github.com/'+REPO+'/tree/'+tag+') · [اجرای تأیید بسته‌ها](https://github.com/'+REPO+'/actions/runs/'+os.environ['GITHUB_RUN_ID']+')\n\n'
    note+='اگر فایل قبلی را دانلود کرده‌اید، APK را دوباره از [صفحهٔ دانلود](https://mcodersir.github.io/dicodePing/#download) دریافت و روی برنامه نصب کنید؛ حذف برنامه لازم نیست.\n\n---\n\n'
    api('PATCH','releases/'+str(release['id']),{'body':note+body})
except BaseException:
    for name in reversed(swapped):
        record=files[name]
        api('PATCH','releases/assets/'+str(record['new_id']),{'name':record['temporary']})
        api('PATCH','releases/assets/'+str(record['old_id']),{'name':name})
    raise
for name in swapped:api('DELETE','releases/assets/'+str(files[name]['old_id']))
_,current=metadata()
assert len(current)==23 and all(current[n]['digest']==r['digest'] for n,r in files.items())
print('PASS published Android revision 2: 5 APKs and checksums; desktop assets unchanged',flush=True)
