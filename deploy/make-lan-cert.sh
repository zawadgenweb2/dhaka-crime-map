#!/usr/bin/env bash
# Self-signed certificate (1 year) for HTTPS on the LAN / Tailscale until a public domain + Let's Encrypt exists.
set -euo pipefail
cd "$(dirname "$0")" && mkdir -p tls && umask 077
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes -keyout tls/key.pem -out tls/cert.pem \
  -subj "/CN=dhaka-crime-map" -addext "subjectAltName=${CERT_SANS:-IP:192.168.1.200,IP:100.64.243.30,DNS:genslr-server}"
chmod 600 tls/key.pem && chmod 644 tls/cert.pem
openssl x509 -in tls/cert.pem -noout -subject -enddate
