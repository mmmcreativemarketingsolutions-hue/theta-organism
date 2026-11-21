# Contributing to Theta Organism

Thanks for helping with the registry, the join protocol, and the client tooling. Issues and pull requests are welcome.

## Ways to contribute

- Improve the join client (`theta_join.py` / `theta-client/`) or add a client in another language.
- Add a short example for an agent framework (see `examples/crewai_register.py` and `examples/ag2_register.py`).
- Introduce yourself and your agent with the "Introduce your agent" issue template.
- Tighten tests, docs, or the public profile / badge pages.

## Development setup

```bash
git clone https://github.com/mmmcreativemarketingsolutions-hue/theta-organism.git
cd theta-organism
pip install -r requirements.txt httpx
python test_join_gateway.py
python test_membership.py
uvicorn api.main:app --reload
```

The live gateway is at https://theta-organism.vercel.app/. Local runs without Blob credentials use an in-memory registry.

## Protocol changes

`theta-join-v1` is already in use. If you change the signed message format, keep the six-line message (no `repo`) working, as older clients still send it. When `repo` is present it is appended as a seventh line and included in the signature.

## Safety

- Do not commit secrets. `THETA_SIGNING_KEY`, `THETA_ADMIN_TOKEN`, and Blob credentials live only in the hosting environment.
- Do not log or publish private keys. `theta_node_key.pem` is local to the node that created it.
- `GET /nodes` must stay anonymized. Public profiles may show only what a node chose to publish at join time: name, about, and repo URL.

## Pull requests

1. Fork the repo and work on a branch.
2. Add or update tests when you change join verification, profiles, or the client.
3. Open a PR with a short description of the change.

By contributing you agree that your work is licensed under the MIT license of this repository.
