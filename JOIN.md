# How to Join Theta Organism

You register a node by signing a short message with your own Ed25519 key and posting it to the live gateway. No application form and no shared secret.

- Instructions (JSON): `GET https://theta-organism.vercel.app/join`
- Full protocol and copy-paste Python / curl examples: [README.md#join-protocol](README.md#join-protocol)
- Scripts: `examples/join_node.py`, `examples/join.sh`

## Local simulation
Clone the repo and run `python run.py` or integrate the `Organism` class from `core.py`. Simulation signals use a local demo key (`THETA_LOCAL_SIM_KEY`) and are separate from the live gateway.

## What happens after you join
- Your node id (derived from your public key) is listed anonymously on `GET /nodes`.
- Your name and description are not published.
- Signal exchange between live nodes is not implemented yet; follow the repo for updates.
