"""Local tests for theta-join-v1, public profiles, and badges.

    pip install httpx
    python test_join_gateway.py
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import unittest

# Force the in-memory registry before importing the app (no production Blob).
os.environ.pop("BLOB_READ_WRITE_TOKEN", None)
os.environ.pop("BLOB_STORE_ID", None)
os.environ.pop("THETA_ADMIN_TOKEN", None)
os.environ.pop("THETA_SIGNING_KEY", None)

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from api import main as gateway
from theta_join import build_message, join_node, node_id_from_public_key, public_key_b64


def _key_and_body(name="test-agent", about="a test node", repo="", layer="surface", ts=None, bad_sig=False):
    sk = Ed25519PrivateKey.generate()
    pk = public_key_b64(sk)
    ts = int(time.time()) if ts is None else ts
    msg = build_message(name, layer, ts, pk, about, repo)
    sig = base64.b64encode(sk.sign(msg if not bad_sig else msg + b"x")).decode()
    body = {
        "name": name,
        "layer": layer,
        "about": about,
        "timestamp": ts,
        "public_key": pk,
        "signature": sig,
    }
    if repo:
        body["repo"] = repo
    raw_pk = base64.b64decode(pk)
    return sk, pk, hashlib.sha256(raw_pk).hexdigest()[:16], body


class JoinGatewayTests(unittest.TestCase):
    def setUp(self):
        gateway.registry = gateway.MemoryRegistry()
        gateway._hits.clear()
        self.client = TestClient(gateway.app)

    def test_join_without_repo_matches_six_line_message(self):
        _, _, node_id, body = _key_and_body()
        r = self.client.post("/join", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["status"], "accepted")
        self.assertEqual(data["node_id"], node_id)
        self.assertTrue(data["profile_url"].endswith(f"/nodes/{node_id}"))
        self.assertTrue(data["badge_url"].endswith(f"/badge/{node_id}.svg"))

    def test_join_with_repo_is_signed_as_seventh_line(self):
        repo = "https://github.com/example/agent"
        _, _, node_id, body = _key_and_body(repo=repo, name="repo-agent", about="has a repo")
        r = self.client.post("/join", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        profile = self.client.get(f"/nodes/{node_id}").json()
        self.assertEqual(profile["name"], "repo-agent")
        self.assertEqual(profile["about"], "has a repo")
        self.assertEqual(profile["repo"], repo)
        self.assertNotIn("public_key", profile)

    def test_invalid_signature_rejected(self):
        _, _, _, body = _key_and_body(bad_sig=True)
        r = self.client.post("/join", json=body)
        self.assertEqual(r.status_code, 401)

    def test_directory_stays_anonymized(self):
        _, _, node_id, body = _key_and_body(name="secret-name", about="do not list this")
        self.assertEqual(self.client.post("/join", json=body).status_code, 200)
        listing = self.client.get("/nodes").json()
        self.assertEqual(listing["count"], 1)
        entry = listing["recent"][0]
        self.assertEqual(entry["id"], node_id)
        self.assertEqual(set(entry), {"id", "layer", "joined_at"})

    def test_profile_json_and_html(self):
        _, _, node_id, body = _key_and_body(name="html-agent", about="shown on the page")
        self.assertEqual(self.client.post("/join", json=body).status_code, 200)
        js = self.client.get(f"/nodes/{node_id}", headers={"Accept": "application/json"})
        self.assertEqual(js.status_code, 200)
        self.assertEqual(js.json()["name"], "html-agent")
        page = self.client.get(f"/nodes/{node_id}", headers={"Accept": "text/html"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers["content-type"])
        self.assertIn("html-agent", page.text)
        self.assertIn("shown on the page", page.text)

    def test_profile_escapes_html(self):
        name = "<script>alert(1)</script>"
        _, _, node_id, body = _key_and_body(name=name, about="ok")
        self.assertEqual(self.client.post("/join", json=body).status_code, 200)
        page = self.client.get(f"/nodes/{node_id}", headers={"Accept": "text/html"})
        self.assertNotIn("<script>alert(1)</script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)

    def test_badge_svg(self):
        _, _, node_id, body = _key_and_body(name="badge-agent")
        self.assertEqual(self.client.post("/join", json=body).status_code, 200)
        r = self.client.get(f"/badge/{node_id}.svg")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/svg+xml", r.headers["content-type"])
        self.assertIn("badge-agent", r.text)
        self.assertIn("<svg", r.text)

    def test_unknown_profile_is_404(self):
        r = self.client.get("/nodes/0123456789abcdef")
        self.assertEqual(r.status_code, 404)

    def test_http_repo_rejected(self):
        _, _, _, body = _key_and_body(repo="http://example.com/agent")
        r = self.client.post("/join", json=body)
        self.assertEqual(r.status_code, 422)

    def test_client_build_message_matches_server(self):
        ts = 1700000000
        pk = "A" * 44
        self.assertEqual(
            build_message("n", "surface", ts, pk, "about"),
            gateway.build_message("n", "surface", ts, pk, "about"),
        )
        self.assertEqual(
            build_message("n", "surface", ts, pk, "about", "https://github.com/x/y"),
            gateway.build_message("n", "surface", ts, pk, "about", "https://github.com/x/y"),
        )

    def test_client_join_against_local_app(self):
        import tempfile
        from unittest.mock import patch
        import urllib.request

        _, _, _, _ = _key_and_body()  # just to keep imports used if needed
        with tempfile.TemporaryDirectory() as tmp:
            key_path = os.path.join(tmp, "key.pem")

            class _Resp:
                def __init__(self, payload, status=200):
                    self._payload = payload
                    self.status = status

                def read(self):
                    import json
                    return json.dumps(self._payload).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            def fake_urlopen(req, timeout=15):
                import json
                body = json.loads(req.data.decode())
                r = self.client.post("/join", json=body)
                return _Resp(r.json(), r.status_code)

            with patch.object(urllib.request, "urlopen", fake_urlopen):
                result = join_node(
                    name="client-agent",
                    about="via client",
                    repo="https://github.com/example/client-agent",
                    key_path=key_path,
                    gateway="https://theta-organism.vercel.app",
                )
            self.assertEqual(result["status"], "accepted")
            self.assertTrue(result["node_id"])
            self.assertTrue(os.path.exists(key_path))
            self.assertEqual(len(result["node_id"]), 16)


if __name__ == "__main__":
    unittest.main()
