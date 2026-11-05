#!/usr/bin/env python3
"""Send real HTTP through the bundled sing-box SOCKS listener using a local fixture."""
import argparse, http.server, json, os, pathlib, socket, struct, subprocess, tempfile, threading, time
parser=argparse.ArgumentParser();parser.add_argument('--root',type=pathlib.Path,required=True);args=parser.parse_args()
binary=args.root.resolve()/'bin'/'sing_box'/('sing-box.exe' if os.name=='nt' else 'sing-box')
def read_exact(stream, count):
    result=bytearray()
    while len(result)<count:
        part=stream.read(count-len(result))
        if not part:raise EOFError('Truncated SOCKS response')
        result.extend(part)
    return bytes(result)
class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=b'independent-singbox-through-proxy'
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture)
threading.Thread(target=server.serve_forever,daemon=True).start()
with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
with tempfile.TemporaryDirectory() as directory:
    config=pathlib.Path(directory)/'config.json';log=pathlib.Path(directory)/'native.log'
    config.write_text(json.dumps({'inbounds':[{'type':'mixed','listen':'127.0.0.1','listen_port':port}], 'outbounds':[{'type':'direct','tag':'direct'}]}))
    with log.open('w') as output:
        process=subprocess.Popen([str(binary),'run','-c',str(config)],stdout=output,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15
            while True:
                if process.poll() is not None: raise RuntimeError(log.read_text())
                try: client=socket.create_connection(('127.0.0.1',port),timeout=1);break
                except OSError:
                    if time.monotonic()>=deadline:raise RuntimeError('sing-box did not listen: '+log.read_text())
                    time.sleep(0.05)
            with client:
                client.settimeout(5)
                stream=client.makefile('rwb',buffering=0)
                stream.write(b'\x05\x01\x00');assert read_exact(stream,2)==b'\x05\x00','SOCKS greeting failed'
                stream.write(b'\x05\x01\x00\x01\x7f\x00\x00\x01'+struct.pack('!H',server.server_port))
                reply=read_exact(stream,4);assert reply[:2]==b'\x05\x00',repr(reply)
                size={1:4,4:16}.get(reply[3]);size=read_exact(stream,1)[0] if size is None else size
                read_exact(stream,size+2)
                stream.write(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                response=stream.read();assert b'independent-singbox-through-proxy' in response,response
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            server.shutdown();server.server_close()
print('PASS independent sing-box: native startup, SOCKS handshake, routed HTTP and process shutdown')
