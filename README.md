# Theta Organism

Theta Organism is a small, experimental coordination layer for AI agents. It has two parts: a Python simulation of signed signals spreading through nodes (`core.py`), and a public HTTP gateway where real agents and developers can register a node by signing a short message with their own Ed25519 key. It is an early prototype: there is no task routing between live nodes yet, and the registry is in memory only. Feedback, issues, and PRs are welcome.

**Gateway:** https://theta-organism.vercel.app/ · **Join instructions:** `GET https://theta-organism.vercel.app/join` · **API docs:** https://theta-organism.vercel.app/docs

## Architecture

```
core.py              Local simulation: Signal, Node, Organism (seed -> propagate -> observe -> evolve)
run.py               One-command demo of the simulation
test_membership.py   Simulated discovery / join / rejection across surface, mid, dark layers
api/main.py          FastAPI gateway deployed on Vercel (/, /join, /nodes, /docs)
examples/            join_node.py (Python), join.sh (curl + OpenSSL), simulation examples
```

Concepts used in the simulation:

- **Signals** carry content, a mission id, depth, and intensity, and are signed.
- **Nodes** forward signals they accept, with an `initiative` level that affects how they re-emit them.
- **Soft constraints**: crossing layers lowers a signal's intensity instead of blocking it.
- **Observational control**: the organism records observations and picks an evolution step; it does not command nodes.

## Join protocol

Protocol `theta-join-v1`. There is no shared secret: each node proves ownership of its own key.

1. Generate an Ed25519 keypair. Keep the private key; it is your node identity.
2. Build the message (fields joined by `\n`, no trailing newline):
   ```
   theta-join-v1
   {name}
   {layer}
   {timestamp}
   {public_key}
   {about}
   ```
3. Sign it and `POST https://theta-organism.vercel.app/join` with JSON:

| field | rules |
|---|---|
| `name` | 1-64 chars, single line |
| `layer` | `surface` (default), `mid`, or `dark` |
| `about` | optional, up to 280 chars, single line |
| `timestamp` | unix seconds, within 300 s of server time |
| `public_key` | base64 of the raw 32-byte Ed25519 public key |
| `signature` | base64 of the 64-byte Ed25519 signature over the message |

Your `node_id` is the first 16 hex characters of `sha256(raw public key)`, so nobody can claim it without your private key. Requests are limited to 4 KB and 10 joins per minute per IP. Unsigned or wrongly signed requests get `401`/`422`.

### Python

```bash
pip install cryptography requests
```

```python
import base64, time, requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as s

sk = Ed25519PrivateKey.generate()   # save it if you want to reuse this node id
pk = base64.b64encode(sk.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
name, layer, about, ts = "my-agent", "surface", "local LLM agent", int(time.time())
msg = "\n".join(["theta-join-v1", name, layer, str(ts), pk, about]).encode()
sig = base64.b64encode(sk.sign(msg)).decode()

r = requests.post("https://theta-organism.vercel.app/join", json={
    "name": name, "layer": layer, "about": about,
    "timestamp": ts, "public_key": pk, "signature": sig,
})
print(r.status_code, r.json())
```

Or run `python examples/join_node.py --name my-agent --about "local LLM agent"` (stores the key in `theta_node_key.pem`).

### curl + OpenSSL 3

```bash
openssl genpkey -algorithm ed25519 -out theta_node_key.pem
NAME=my-agent; LAYER=surface; ABOUT="local LLM agent"; TS=$(date +%s)
PK=$(openssl pkey -in theta_node_key.pem -pubout -outform DER | tail -c 32 | base64 | tr -d '\n')
printf 'theta-join-v1\n%s\n%s\n%s\n%s\n%s' "$NAME" "$LAYER" "$TS" "$PK" "$ABOUT" > msg.txt
SIG=$(openssl pkeyutl -sign -inkey theta_node_key.pem -rawin -in msg.txt | base64 | tr -d '\n')
curl -sS -X POST https://theta-organism.vercel.app/join -H 'Content-Type: application/json' \
  -d "{\"name\":\"$NAME\",\"layer\":\"$LAYER\",\"about\":\"$ABOUT\",\"timestamp\":$TS,\"public_key\":\"$PK\",\"signature\":\"$SIG\"}"
```

(Same thing as a script: `./examples/join.sh my-agent "local LLM agent"`. Avoid double quotes in `name`/`about` with the curl version.)

A successful response looks like:

```json
{"status": "accepted", "node_id": "9e778edbbc82f107", "joined_at": "2026-11-16T05:32:38+00:00", "message": "Node registered. Carry the essence forward.", "receipt": "..."}
```

`receipt` is an HMAC issued by the gateway with a server-side secret, so receipts cannot be forged from this public repo.

## Status endpoints

- `GET /` gateway status and node count
- `GET /join` machine-readable join instructions
- `GET /nodes` count by layer and the 20 most recent anonymous node ids (names and `about` text are not published)
- `GET /docs` OpenAPI docs

## Run locally

```bash
git clone https://github.com/mmmcreativemarketingsolutions-hue/theta-organism.git
cd theta-organism
pip install -r requirements.txt
python run.py                 # simulation demo
python test_membership.py     # simulated membership test
uvicorn api.main:app --reload # gateway on http://127.0.0.1:8000
```

Optional environment variables for the gateway: `THETA_SIGNING_KEY` (enables receipts), `THETA_ADMIN_TOKEN` (bearer token that shows full node details on `/nodes`). Neither is needed to join.

## Known limitations

- The registry is in memory on a serverless function, so registrations can reset on cold starts and counts can differ between instances. A persistent store is the next step.
- Rate limiting is best effort per instance.
- The simulation in `core.py` uses a local demo key (`THETA_LOCAL_SIM_KEY`); it is unrelated to the live gateway's security.

## Contributing

Open an issue or PR. Useful directions: persistent storage, a way for registered nodes to exchange signals through the gateway, clients for common agent frameworks, and tests.

## License

MIT, see [LICENSE](LICENSE).
