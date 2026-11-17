#!/usr/bin/env python3
"""Check every pinned Serverless v62 profile with the packaged Xray binary."""
import argparse, json, os, pathlib, subprocess, tempfile
p=argparse.ArgumentParser();p.add_argument('--xray',type=pathlib.Path,required=True);args=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
profiles=json.loads((root/'assets/serverless/v62.json').read_text())
assert len(profiles)>=3
with tempfile.TemporaryDirectory(prefix='dicode-serverless-') as tmp:
 for index,profile in enumerate(profiles):
  assert 'v62' in profile['remarks']
  path=pathlib.Path(tmp)/f'{index}.json';path.write_text(json.dumps(profile))
  env=os.environ.copy();asset_root=args.xray.resolve().parent.parent
  if (asset_root/'geosite.dat').is_file():env['XRAY_LOCATION_ASSET']=str(asset_root)
  result=subprocess.run([str(args.xray.resolve()),'run','-test','-c',str(path)],capture_output=True,text=True,timeout=25,env=env)
  if result.returncode:raise RuntimeError(profile['remarks']+': '+result.stdout+result.stderr)
  print('PASS native Xray configuration:',profile['remarks'])
