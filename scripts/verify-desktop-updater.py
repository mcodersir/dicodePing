"""Run the actual published updater against an isolated portable installation."""
import argparse, pathlib, tempfile, subprocess, zipfile, shutil, os, time
p=argparse.ArgumentParser();p.add_argument('--tool',required=True,type=pathlib.Path);a=p.parse_args()
tool=a.tool.resolve()
with tempfile.TemporaryDirectory(prefix='dicode-update-') as tmp:
 root=pathlib.Path(tmp);project=root/'stub';project.mkdir()
 (project/'stub.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><AssemblyName>DicodePing</AssemblyName><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
 (project/'Program.cs').write_text('System.IO.File.WriteAllText(System.IO.Path.Combine(System.AppContext.BaseDirectory,"update-restarted.txt"),"updated");')
 subprocess.run(['dotnet','publish',str(project/'stub.csproj'),'-c','Release','-o',str(root/'payload')],check=True)
 for prefix in ['', 'DicodePing/', 'DicodePing.app/Contents/MacOS/']:
  install=root/('root' if not prefix else 'mac/DicodePing.app/Contents/MacOS' if prefix.endswith('MacOS/') else 'nested');install.mkdir(parents=True)
  updater=install/tool.name;shutil.copy2(tool,updater);updater.chmod(0o755)
  (install/'bin').mkdir();(install/'bin/core-version.txt').write_text('old')
  (install/'guiConfigs').mkdir();(install/'guiConfigs/account.json').write_text('retained-account')
  archive=root/('root.zip' if not prefix else 'mac.zip' if prefix.endswith('MacOS/') else 'nested.zip')
  with zipfile.ZipFile(archive,'w') as z:
   for file in (root/'payload').iterdir():
    if file.is_file():z.write(file,prefix+file.name)
   if prefix.endswith('MacOS/'):
    z.writestr('DicodePing.app/Contents/Info.plist','new-metadata')
    z.writestr('README.txt','Move the app to Applications')
   z.writestr(prefix+'bin/core-version.txt','new')
   z.writestr(prefix+'guiConfigs/account.json','must-not-overwrite')
  subprocess.run([str(updater),str(archive)],cwd=install,check=True,timeout=45)
  marker=install/'update-restarted.txt'
  deadline=time.monotonic()+10
  while not marker.exists() and time.monotonic()<deadline:time.sleep(.2)
  assert marker.read_text()=='updated'
  if prefix.endswith('MacOS/'):assert (install.parent/'Info.plist').read_text()=='new-metadata'
  assert (install/'bin/core-version.txt').read_text()=='new'
  assert (install/'guiConfigs/account.json').read_text()=='retained-account'
  print('PASS real standalone updater, '+('nested' if prefix else 'root')+' ZIP, core replacement, preserved account, app restart')
