#!/usr/bin/env python3
"""Exercise real Linux TUN traffic with a /32 route and a local SOCKS fixture."""
import argparse, json, os, pathlib, socket, socketserver, struct, subprocess, tempfile, threading, time
p=argparse.ArgumentParser();p.add_argument('--xray',type=pathlib.Path,required=True);args=p.parse_args()
assert os.geteuid()!=0, 'Run the test as the ordinary desktop user after setting core capabilities'
def exact(stream,n):
 data=stream.read(n)
 if len(data)!=n:raise EOFError('Truncated SOCKS request')
 return data
class Fixture(socketserver.StreamRequestHandler):
 def handle(self):
  self.connection.settimeout(10)
  version,count=exact(self.rfile,2);assert version==5;exact(self.rfile,count);self.wfile.write(b'\x05\x00');self.wfile.flush()
  version,command,_,kind=exact(self.rfile,4);assert (version,command)==(5,1)
  exact(self.rfile,{1:4,4:16}.get(kind,0) or exact(self.rfile,1)[0]);exact(self.rfile,2)
  self.wfile.write(b'\x05\x00\x00\x01'+b'\0'*6);self.wfile.flush()
  header=b''
  while not header.endswith(b'\r\n\r\n'):
   header+=exact(self.rfile,1);assert len(header)<16384
  body=b'linux-tun-ok';self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\n'+body);self.wfile.flush()
server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='dicode-linux-tun-') as tmp:
 tmp=pathlib.Path(tmp);config=tmp/'tun.json';log=tmp/'tun.log'
 config.write_text(json.dumps({'log':{'loglevel':'info'},'inbounds':[{'protocol':'tun','tag':'tun','settings':{'name':'dicode_ci_'+str(os.getpid()),'gateway':['172.31.254.1/30'],'MTU':1400,'autoSystemRoutingTable':['198.18.254.1/32'],'autoSystemDnsToGateway':False}}],'outbounds':[{'protocol':'socks','tag':'proxy','settings':{'servers':[{'address':'127.0.0.1','port':server.server_address[1]}]}}]}))
 with log.open('w+') as output:
  child=subprocess.Popen([str(args.xray.resolve()),'run','-c',str(config)],stdout=output,stderr=output)
  try:
   deadline=time.monotonic()+25;ready=False
   while time.monotonic()<deadline:
    output.flush();text=log.read_text()
    if child.poll() is not None:raise RuntimeError('TUN core exited: '+text)
    if ' started' in text and 'core: Xray' in text:ready=True;break
    time.sleep(.1)
   assert ready,'No TUN readiness: '+log.read_text()
   with socket.create_connection(('198.18.254.1',18080),timeout=10) as connection:
    connection.sendall(b'GET /linux-tun HTTP/1.1\r\nHost: local.test\r\nConnection: close\r\n\r\n');data=b''
    while True:
     chunk=connection.recv(4096)
     if not chunk:break
     data+=chunk
    assert data.endswith(b'linux-tun-ok'),data
   print('PASS Linux TUN starts as ordinary user and routes real HTTP traffic through its core')
  finally:
   child.terminate()
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:child.kill();child.wait()
server.shutdown();server.server_close()
