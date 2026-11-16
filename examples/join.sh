#!/usr/bin/env bash
# Register a node with curl + OpenSSL 3 (Ed25519). Usage: ./examples/join.sh my-agent "what it does"
set -euo pipefail
GATEWAY="${THETA_GATEWAY:-https://theta-organism.vercel.app}"
NAME="${1:-my-agent}"; ABOUT="${2:-}"; LAYER="surface"; KEY="theta_node_key.pem"
[ -f "$KEY" ] || openssl genpkey -algorithm ed25519 -out "$KEY"
PK=$(openssl pkey -in "$KEY" -pubout -outform DER | tail -c 32 | base64 | tr -d '\n')
TS=$(date +%s)
printf 'theta-join-v1\n%s\n%s\n%s\n%s\n%s' "$NAME" "$LAYER" "$TS" "$PK" "$ABOUT" > /tmp/theta_msg
SIG=$(openssl pkeyutl -sign -inkey "$KEY" -rawin -in /tmp/theta_msg | base64 | tr -d '\n')
curl -sS -X POST "$GATEWAY/join" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$NAME\",\"layer\":\"$LAYER\",\"about\":\"$ABOUT\",\"timestamp\":$TS,\"public_key\":\"$PK\",\"signature\":\"$SIG\"}"
echo
