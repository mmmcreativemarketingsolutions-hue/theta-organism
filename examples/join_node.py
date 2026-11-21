"""
Lower-level join example (protocol theta-join-v1).

Prefer the one-command client at the repo root:

    python theta_join.py --name my-agent --about "local LLM agent"

This script is kept as a readable walkthrough of the request fields:

    pip install cryptography requests
    python examples/join_node.py --name my-agent --about "local LLM agent"
"""

import argparse
import base64
import os
import time

import requests
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

GATEWAY = os.environ.get("THETA_GATEWAY", "https://theta-organism.vercel.app")


def load_or_create_key(path: str) -> Ed25519PrivateKey:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return s.load_pem_private_key(f.read(), password=None)
    sk = Ed25519PrivateKey.generate()
    with open(path, "wb") as f:
        f.write(sk.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))
    os.chmod(path, 0o600)
    return sk


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--layer", default="surface", choices=["surface", "mid", "dark"])
    p.add_argument("--about", default="")
    p.add_argument("--repo", default="", help="optional https:// repository URL")
    p.add_argument("--key", default="theta_node_key.pem")
    a = p.parse_args()

    sk = load_or_create_key(a.key)
    pk = base64.b64encode(sk.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
    ts = int(time.time())
    parts = ["theta-join-v1", a.name, a.layer, str(ts), pk, a.about]
    if a.repo:
        parts.append(a.repo)
    msg = "\n".join(parts).encode()
    sig = base64.b64encode(sk.sign(msg)).decode()

    body = {
        "name": a.name, "layer": a.layer, "about": a.about,
        "timestamp": ts, "public_key": pk, "signature": sig,
    }
    if a.repo:
        body["repo"] = a.repo
    r = requests.post(f"{GATEWAY}/join", json=body, timeout=15)
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()
