#!/usr/bin/env python3
"""Exercise the actual CLI/native-core/proxy path with local HTTP fixtures."""
import argparse,json,pathlib,subprocess,tempfile,threading,http.server,socket,time,signal,os,sys
parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=pathlib.Path);parser.add_argument('--dotnet');args=parser.parse_args()
root=args.root.resolve();command=([args.dotnet,str(root/'dicodeping.dll')] if args.dotnet else [str(root/'dicodeping')])
def freeport():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self): self.send_response(200);self.end_headers();self.wfile.write(b'Dicode CLI native test')
 def log_message(self,*_):pass
http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=http.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='dicode-cli-verify-') as folder:
 data=pathlib.Path(folder)/'data';serverport=freeport()
 def call(*words):
  p=subprocess.run(command+list(words)+['--data',str(data),'--verbose'],capture_output=True,text=True,timeout=90)
  if p.stderr:print(p.stderr,file=sys.stderr)
  if p.returncode!=0:raise RuntimeError(p.stderr+'\n'+p.stdout)
  return p.stdout
 for name,outbound in [('good',{'type':'direct','tag':'proxy'}),('failed',{'type':'socks','tag':'proxy','server':'127.0.0.1','server_port':9})]:
  file=pathlib.Path(folder)/(name+'.json');file.write_text(json.dumps({'remarks':name,'inbounds':[{'type':'mixed','tag':'socks','listen':'127.0.0.1','listen_port':serverport}],'outbounds':[outbound],'route':{'final':'proxy'}}));call('import',str(file))
 configfile=data/'guiConfigs'/'DicodePingConfig.json';config=json.loads(configfile.read_text(encoding='utf-8-sig'))
 config['SpeedTestItem']['SpeedPingTestUrl']=f'http://127.0.0.1:{http.server_port}/'
 configfile.write_text(json.dumps(config))
 # A single custom profile must use the isolated probe too, rather than failing
 # because it cannot be included in the shared batch configuration.
 singles=pathlib.Path(folder)/'single'
 file=pathlib.Path(folder)/'good.json'
 singlecmd=command+['import',str(file),'--data',str(singles),'--verbose']
 subprocess.run(singlecmd,check=True,capture_output=True,text=True,timeout=30)
 scfile=singles/'guiConfigs'/'DicodePingConfig.json';sc=json.loads(scfile.read_text(encoding='utf-8-sig'))
 sc['SpeedTestItem']['SpeedPingTestUrl']=f'http://127.0.0.1:{http.server_port}/';scfile.write_text(json.dumps(sc))
 sp=subprocess.run(command+['ping','--data',str(singles),'--verbose'],capture_output=True,text=True,timeout=60)
 assert sp.returncode==0 and any(json.loads(l).get('latency',0)>0 for l in sp.stdout.splitlines() if l.startswith('{')),sp.stderr+'\n'+sp.stdout
 output=call('ping');probes=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
 assert len(probes)==2 and max(p['completed'] for p in probes)==2,output
 profiles=json.loads(call('profiles'));assert profiles[0]['name']=='good' and profiles[0]['latency']>0 and profiles[1]['latency']<=0,profiles
 log=pathlib.Path(folder)/'connect.log'
 with log.open('w') as stderr:
  process=subprocess.Popen(command+['connect','--best','--data',str(data),'--verbose'],stdout=subprocess.PIPE,stderr=stderr,start_new_session=True)
  try:
   deadline=time.monotonic()+30
   while 'Running good.' not in log.read_text():
    if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError(log.read_text())
    time.sleep(.1)
   # Curl performs a SOCKS handshake, then requests actual data through both native cores.
   proxyport=config['Inbound'][0]['LocalPort']
   result=subprocess.run(['curl','--noproxy','','--fail','--max-time','10','--socks5-hostname',f'127.0.0.1:{proxyport}',f'http://127.0.0.1:{http.server_port}/'],capture_output=True,text=True)
   assert result.returncode==0 and 'Dicode CLI native test' in result.stdout,result.stderr
   process.send_signal(signal.SIGINT);process.wait(timeout=15)
   assert process.returncode in (0,130),log.read_text()
   for port in [serverport,proxyport]:
    with socket.socket() as s:assert s.connect_ex(('127.0.0.1',port))!=0,'Core listener survived Ctrl+C'
  finally:
   if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
http.shutdown();print('PASS CLI: native JSON import, real HTTP latency, failed-last sorting, cached best, two-core proxy traffic and Ctrl+C cleanup')
