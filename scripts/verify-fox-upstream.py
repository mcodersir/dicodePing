#!/usr/bin/env python3
"""Verify the pinned source and the exact reviewed integration adaptations."""
import pathlib,hashlib,json
root=pathlib.Path(__file__).resolve().parents[1]/'apps/fox-helper'
pin=json.loads((root/'UPSTREAM.json').read_text())
assert pin['commit']=='80ff467764d90d95ef961bd112b78a85a399b1bf'
for name,digest in pin['files'].items():
    data=(root/'internal'/name).read_bytes()
    if name in pin['adapted_files']:
        assert hashlib.sha256(data).hexdigest()==pin['adapted_files'][name],name
    else:
        data=data.replace(b'dicodeping/fox/internal/',b'github.com/armanlife/arman-vpn-client/core/internal/')
        assert hashlib.sha256(data).hexdigest()==digest,name
assert (root/'LICENSE-ArmanVPN.txt').read_text().startswith('                    GNU GENERAL PUBLIC LICENSE')
assert 'fxa.OAuthToken' in (root/'main.go').read_text() and 'proxy.NewController' in (root/'main.go').read_text()
print('PASS pinned Arman v1.0.11 source, OAuth recovery, transport integration and attribution:',len(pin['files']),'files')
