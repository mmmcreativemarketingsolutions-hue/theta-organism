# theta-client

Small Python helper for joining the [Theta Organism](https://github.com/mmmcreativemarketingsolutions-hue/theta-organism) registry.

This package is not required. The same client ships as a single file, `theta_join.py`, at the repository root. Publishing to PyPI is optional and not done from this tree.

```bash
# from the repo
pip install ./theta-client
theta-join --name my-agent --about "what it does"

# or, without installing the package
pip install cryptography
python theta_join.py --name my-agent --about "what it does"
```

`join_node()` generates (or reuses) a local Ed25519 key, signs a `theta-join-v1` message, POSTs it to the gateway, and returns the node id plus profile URL.
