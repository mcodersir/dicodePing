#!/usr/bin/env bash
set -euo pipefail
fixture_root=/tmp/dicode-browser-fixture
mkdir -p "$fixture_root"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -keyout "$fixture_root/root.key" -out "$fixture_root/root.crt" -subj '/CN=Dicode isolated CI root' -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign' 2>/dev/null
openssl req -newkey rsa:2048 -nodes -keyout "$fixture_root/leaf.key" -out "$fixture_root/leaf.csr" -subj '/CN=accounts.firefox.com' 2>/dev/null
cat > "$fixture_root/leaf.ext" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:accounts.firefox.com
EXT
openssl x509 -req -in "$fixture_root/leaf.csr" -CA "$fixture_root/root.crt" -CAkey "$fixture_root/root.key" -CAcreateserial -out "$fixture_root/leaf.crt" -days 1 -extfile "$fixture_root/leaf.ext" 2>/dev/null
sudo cp "$fixture_root/root.crt" /usr/local/share/ca-certificates/dicode-isolated-ci.crt
sudo update-ca-certificates >/dev/null
