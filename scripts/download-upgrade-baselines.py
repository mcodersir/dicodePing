"""Retrieve official upgrade fixtures, preserving a removed release's signed build."""
import argparse,hashlib,json,os,pathlib,re,shutil,tempfile,time,urllib.request,urllib.error,zipfile
REPO='mcodersir/dicodePing'
SOURCE=pathlib.Path(__file__).resolve().parents[1]
EXPECTED_SOURCE='2d223dc47a9c3e8b71072d722830a870ffff302e'
OLD_SOURCE='a4fa3962a1714fedfc55a82ca8ffdcd3d096a6d6'
TOKEN=os.environ['GH_TOKEN']
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
def open_url(url,auth=False):
 headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json'} if auth else {}
 req=urllib.request.Request(url,headers=headers)
 try:return urllib.request.build_opener(NoRedirect()).open(req,timeout=90)
 except urllib.error.HTTPError as e:
  if e.code not in (301,302,303,307,308):raise
  target=e.headers['Location']
  if not target.startswith('https://'):raise RuntimeError('Insecure artifact redirect')
  return urllib.request.urlopen(target,timeout=90)
def api(path):
 with open_url('https://api.github.com/repos/'+REPO+'/'+path,True) as response:return json.load(response)
def fetch(url,destination,auth=False):
 for attempt in range(4):
  try:
   with open_url(url,auth) as response,open(destination,'wb') as output:shutil.copyfileobj(response,output,1024*1024)
   return
  except urllib.error.HTTPError as e:
   if e.code==404:raise
   if attempt==3:raise
   time.sleep(2*(attempt+1))
def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def archived985(abi,destination):
 run=api('actions/runs/42285296238')
 assert run['head_sha']==OLD_SOURCE and run['conclusion']=='success'
 artifact=api('actions/artifacts/13538831501')
 assert not artifact['expired'] and artifact['name']=='android'
 assert artifact['workflow_run']['head_sha']==OLD_SOURCE
 filename='DicodePing-4.9.985-'+abi+'.apk'
 with tempfile.TemporaryDirectory() as directory:
  archive=pathlib.Path(directory)/'android.zip'
  fetch(artifact['archive_download_url'],archive,True)
  assert 'sha256:'+digest(archive)==artifact['digest'],'Archived build digest mismatch'
  with zipfile.ZipFile(archive) as z:
   matches=[n for n in z.namelist() if pathlib.PurePosixPath(n).name==filename]
   assert len(matches)==1,filename
   checksum_names=[n for n in z.namelist() if pathlib.PurePosixPath(n).name=='SHA256SUMS-android.txt']
   assert len(checksum_names)==1
   checks={}
   for line in z.read(checksum_names[0]).decode('utf-8-sig').splitlines():
    match=re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?(.+)',line.strip());assert match
    checks[match[2]]=match[1].lower()
   with z.open(matches[0]) as input,open(destination,'wb') as output:shutil.copyfileobj(input,output,1024*1024)
   assert digest(destination)==checks[filename]
 print('Verified archived signed baseline 4.9.985',abi,flush=True)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--abi',required=True);parser.add_argument('--versions',default='');parser.add_argument('--destination',required=True);args=parser.parse_args()
 run=api('actions/runs/42329122070');assert run['head_sha']==EXPECTED_SOURCE
 for rid in [42329028191,42329028212]:
  checked=api('actions/runs/'+str(rid));assert checked['head_sha']==EXPECTED_SOURCE and checked['conclusion']=='success'
 target=pathlib.Path(args.destination);target.mkdir(parents=True,exist_ok=True)
 for version in args.versions.split():
  output=target/(version+'.apk')
  url='https://github.com/'+REPO+'/releases/download/v'+version+'/DicodePing-'+version+'-'+args.abi+'.apk'
  try:fetch(url,output)
  except urllib.error.HTTPError as error:
   if error.code!=404 or version!='4.9.985':raise
   archived985(args.abi,output)
  print('Ready official baseline',version,args.abi,flush=True)
if __name__=='__main__':main()
