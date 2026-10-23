#!/usr/bin/env python3
"""Exercise the production Windows Xray TUN with a local TLS/WebSocket VLESS exit.

Only the documentation subnet is routed into this test TUN. The fixture's
self-signed certificate/key are test data, never account or production keys.
"""
import argparse
import http.server
import ipaddress
import json
import os
import pathlib
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=pathlib.Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
cli = root / 'dicodeping.exe'
xray = root / 'bin/xray/xray.exe'
assert os.name == 'nt', 'This check requires the Windows Wintun driver.'

def freeport():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'Dicode native VLESS TLS WebSocket traffic'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass

http = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=http.serve_forever, daemon=True).start()
fixtures = pathlib.Path('apps/android/app/src/androidTest/assets').resolve()
with tempfile.TemporaryDirectory(prefix='dicode-vless-native-') as folder:
    folder = pathlib.Path(folder)
    data = folder / 'data'
    endpoint = freeport()
    user = str(uuid.uuid4())
    config = {
        'log': {'loglevel': 'debug'},
        'inbounds': [{'listen': '127.0.0.1', 'port': endpoint, 'protocol': 'vless',
                      'settings': {'clients': [{'id': user}], 'decryption': 'none'},
                      'streamSettings': {'network': 'ws', 'security': 'tls',
                                         'wsSettings': {'path': '/native-fixture'},
                                         'tlsSettings': {'alpn': ['http/1.1'], 'certificates': [{
                                             'certificateFile': str(fixtures / 'native-fixture-cert.pem.txt'),
                                             'keyFile': str(fixtures / 'native-fixture-key.pem.txt')} ]}}}],
        'outbounds': [{'protocol': 'freedom', 'settings': {
            'redirect': f'127.0.0.1:{http.server_port}',
            'finalRules': [{'action': 'allow', 'ip': ['127.0.0.1/32']}]}}],
    }
    server_config = folder / 'server.json'
    server_config.write_text(json.dumps(config))
    link = folder / 'profile.txt'
    link.write_text(f'vless://{user}@127.0.0.1:{endpoint}?encryption=none&security=tls&sni=localhost&allowInsecure=1&alpn=http%2F1.1&type=ws&path=%2Fnative-fixture#Native-VLESS-fixture')
    with (folder / 'server.log').open('w') as server_log, (folder / 'client.log').open('w') as client_log:
        server = subprocess.Popen([str(xray), 'run', '-c', str(server_config)], stdout=server_log, stderr=server_log)
        client = None
        try:
            result = subprocess.run([str(cli), 'import', str(link), '--data', str(data), '--verbose'], capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stderr
            listed = subprocess.run([str(cli), 'profiles', '--data', str(data), '--verbose'], capture_output=True, text=True, timeout=60)
            assert listed.returncode == 0, listed.stderr
            profiles = json.loads(listed.stdout)
            profile_id = next(p['id'] for p in profiles if p['name'] == 'Native-VLESS-fixture')
            settings_file = data / 'guiConfigs/DicodePingConfig.json'
            settings = json.loads(settings_file.read_text(encoding='utf-8-sig'))
            settings['TunModeItem']['EnableLegacyProtect'] = False
            settings['TunModeItem']['Mtu'] = 1500
            settings['TunModeItem']['AutoRoute'] = True
            settings['TunModeItem']['RouteExcludeAddress'] = [
                str(net) for net in ipaddress.ip_network('0.0.0.0/0').address_exclude(ipaddress.ip_network('192.0.2.0/24'))
            ] + ['::/0']
            settings['SpeedTestItem']['SpeedPingTestUrl'] = f'http://192.0.2.1:{http.server_port}/'
            settings_file.write_text(json.dumps(settings))
            client = subprocess.Popen([str(cli), 'connect', profile_id, '--tun', '--data', str(data), '--verbose'],
                                      stdout=subprocess.DEVNULL, stderr=client_log,
                                      creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            deadline = time.monotonic() + 40
            while 'Running Native-VLESS-fixture.' not in (folder / 'client.log').read_text(errors='replace'):
                if client.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError((folder / 'client.log').read_text(errors='replace'))
                time.sleep(.1)
            generated = [json.loads(p.read_text(encoding='utf-8-sig')) for p in data.rglob('config.json')]
            assert any(any(i.get('protocol') == 'tun' for i in c.get('inbounds', [])) for c in generated), 'Ordinary profile was wrapped instead of using native TUN'
            result = subprocess.run(['curl.exe', '--noproxy', '*', '--fail', '--max-time', '10',
                                     f'http://192.0.2.1:{http.server_port}/native-tun'], capture_output=True, text=True, timeout=15)
            assert result.returncode == 0 and 'Dicode native VLESS TLS WebSocket traffic' in result.stdout, result.stderr + '\n' + (folder / 'client.log').read_text(errors='replace') + '\n' + (folder / 'server.log').read_text(errors='replace')
            try:
                client.send_signal(signal.CTRL_BREAK_EVENT)
                client.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                # CI may not attach a console. Closing the owner process closes
                # its Windows job and terminates the owned TUN core as well.
                client.terminate()
                client.wait(timeout=15)
            print('PASS Windows native TUN: imported VLESS, TLS/WebSocket handshake, kernel-routed HTTP traffic and shutdown')
        finally:
            if client is not None and client.poll() is None:
                client.kill()
                client.wait()
            server.terminate()
            server.wait(timeout=10)
http.shutdown()
