"""
Theta Organism Gateway (surface layer).

Join protocol v1 (public, no shared secret):
  1. A node generates its own Ed25519 keypair.
  2. It builds the message:
       "theta-join-v1\n{name}\n{layer}\n{timestamp}\n{public_key}\n{about}"
  3. It signs the message with its private key and POSTs JSON to /join.
  4. The gateway verifies the signature against the declared public key.
     node_id = first 16 hex chars of sha256(raw public key), so an identity
     cannot be claimed without the matching private key.

No secret lives in this repository. Optional server-side secrets come from
environment variables only:
  THETA_SIGNING_KEY  - HMAC key used to issue join receipts (if unset, no receipt)
  THETA_ADMIN_TOKEN  - bearer token that unlocks full node details on GET /nodes
                       and DELETE /nodes/{node_id}
  BLOB_READ_WRITE_TOKEN (or BLOB_STORE_ID with Vercel OIDC)
                     - Vercel Blob store for the persistent node registry.
                       If unset, the registry falls back to process memory
                       (fine for local runs, lost on restart).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

PUBLIC_URL = "https://theta-organism.vercel.app"
REPO_URL = "https://github.com/mmmcreativemarketingsolutions-hue/theta-organism"
PROTOCOL = "theta-join-v1"
LAYERS = ("surface", "mid", "dark")

MAX_BODY_BYTES = 4096          # whole request body
MAX_TIMESTAMP_SKEW = 300       # seconds
RATE_LIMIT_PER_MIN = 10        # POST /join per client IP (best effort, per instance)
MAX_NODES = 5000

SIGNING_KEY = os.environ.get("THETA_SIGNING_KEY", "")
ADMIN_TOKEN = os.environ.get("THETA_ADMIN_TOKEN", "")

app = FastAPI(title="Theta Organism Gateway", version="0.3.0")

_hits: Dict[str, Deque[float]] = defaultdict(deque)
log = logging.getLogger("theta")


class StorageUnavailable(Exception):
    pass


class MemoryRegistry:
    """Process-local registry (local runs / no storage configured)."""

    kind = "memory"

    def __init__(self):
        self._nodes: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, node_id: str) -> Optional[dict]:
        return self._nodes.get(node_id)

    def add(self, record: dict) -> Optional[dict]:
        """Insert record; return the existing record instead if node_id is taken."""
        with self._lock:
            existing = self._nodes.get(record["id"])
            if existing:
                return existing
            if len(self._nodes) >= MAX_NODES:
                raise OverflowError
            self._nodes[record["id"]] = record
            return None

    def summary(self) -> List[dict]:
        """Anonymous entries {id, layer, joined_at}, oldest first."""
        return [{"id": n["id"], "layer": n["layer"], "joined_at": n["joined_at"]} for n in self._nodes.values()]

    def full(self, node_id: str) -> Optional[dict]:
        return self._nodes.get(node_id)

    def delete(self, node_id: str) -> bool:
        with self._lock:
            return self._nodes.pop(node_id, None) is not None


class BlobRegistry:
    """Persistent registry on a private Vercel Blob store.

    One blob per node:  theta/nodes/{node_id}.{layer}.{joined_epoch}.json
    (full record inside, anonymous fields encoded in the pathname), plus an
    index blob theta/index.json with the anonymous summary so GET /nodes is a
    single cached read. The index is always rebuilt from a listing of the node
    blobs, so node blobs are the source of truth.
    """

    kind = "vercel-blob"
    PREFIX = "theta/nodes/"
    INDEX = "theta/index.json"
    SUMMARY_TTL = 30  # seconds a warm instance reuses its index copy

    def __init__(self):
        from vercel.blob import sync as vblob  # imported lazily: optional dependency
        self.b = vblob
        self._summary: Optional[List[dict]] = None
        self._summary_at = 0.0
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------------
    def _path(self, rec: dict) -> str:
        epoch = int(datetime.fromisoformat(rec["joined_at"]).timestamp())
        return f"{self.PREFIX}{rec['id']}.{rec['layer']}.{epoch}.json"

    @staticmethod
    def _parse(pathname: str) -> Optional[dict]:
        try:
            node_id, layer, epoch, _ = pathname.rsplit("/", 1)[1].split(".")
            joined = datetime.fromtimestamp(int(epoch), timezone.utc).isoformat(timespec="seconds")
            return {"id": node_id, "layer": layer, "joined_at": joined}
        except Exception:
            return None

    def _list(self, prefix: str) -> List[dict]:
        try:
            out = []
            for item in self.b.query_blobs(prefix=prefix):
                entry = self._parse(item.pathname)
                if entry:
                    entry["_path"] = item.pathname
                    out.append(entry)
            return out
        except Exception as e:  # network / credentials
            log.exception("blob list failed")
            raise StorageUnavailable(str(e))

    def _rebuild_index(self) -> List[dict]:
        entries = self._list(self.PREFIX)
        entries.sort(key=lambda e: e["joined_at"])
        summary = [{k: e[k] for k in ("id", "layer", "joined_at")} for e in entries]
        try:
            self.b.put_blob(
                self.INDEX, json.dumps(summary).encode(), access="private",
                content_type="application/json", allow_overwrite=True, cache_control_max_age=60,
            )
        except Exception:
            log.exception("index write failed (summary still served from listing)")
        with self._lock:
            self._summary, self._summary_at = summary, time.time()
        return summary

    def _find(self, node_id: str) -> Optional[dict]:
        hits = self._list(f"{self.PREFIX}{node_id}.")
        return hits[0] if hits else None

    # -- registry API ------------------------------------------------------
    def get(self, node_id: str) -> Optional[dict]:
        hit = self._find(node_id)
        if hit:
            hit.pop("_path", None)
        return hit

    def add(self, record: dict) -> Optional[dict]:
        existing = self.get(record["id"])
        if existing:
            return existing
        if len(self.summary()) >= MAX_NODES:
            raise OverflowError
        try:
            self.b.put_blob(
                self._path(record), json.dumps(record).encode(), access="private",
                content_type="application/json", allow_overwrite=False,
            )
        except Exception as e:
            existing = self.get(record["id"])  # lost a race with a parallel join
            if existing:
                return existing
            log.exception("blob put failed")
            raise StorageUnavailable(str(e))
        self._rebuild_index()
        return None

    def summary(self) -> List[dict]:
        with self._lock:
            if self._summary is not None and time.time() - self._summary_at < self.SUMMARY_TTL:
                return self._summary
        try:
            data = json.loads(self.b.get_blob(self.INDEX, access="private").body)
            with self._lock:
                self._summary, self._summary_at = data, time.time()
            return data
        except Exception:
            return self._rebuild_index()  # first run, or index missing

    def full(self, node_id: str) -> Optional[dict]:
        hit = self._find(node_id)
        if not hit:
            return None
        try:
            return json.loads(self.b.get_blob(hit["_path"], access="private").body)
        except Exception:
            return {k: hit[k] for k in ("id", "layer", "joined_at")}

    def delete(self, node_id: str) -> bool:
        hits = self._list(f"{self.PREFIX}{node_id}.")
        if not hits:
            return False
        try:
            self.b.delete_blob([h["_path"] for h in hits])
        except Exception as e:
            raise StorageUnavailable(str(e))
        self._rebuild_index()
        return True


def _make_registry():
    if os.environ.get("BLOB_READ_WRITE_TOKEN") or os.environ.get("BLOB_STORE_ID"):
        try:
            return BlobRegistry()
        except Exception:
            log.exception("Vercel Blob unavailable, falling back to memory")
    return MemoryRegistry()


registry = _make_registry()

_LINE_SAFE = re.compile(r"^[^\r\n]*$")


def build_message(name: str, layer: str, timestamp: int, public_key: str, about: str) -> bytes:
    return "\n".join([PROTOCOL, name, layer, str(timestamp), public_key, about]).encode("utf-8")


class JoinRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    layer: str = Field("surface", max_length=16)
    about: str = Field("", max_length=280)
    timestamp: int
    public_key: str = Field(..., min_length=40, max_length=64, description="base64 raw Ed25519 public key (32 bytes)")
    signature: str = Field(..., min_length=80, max_length=100, description="base64 Ed25519 signature (64 bytes)")

    @field_validator("name", "about")
    @classmethod
    def single_line(cls, v: str) -> str:
        if not _LINE_SAFE.match(v):
            raise ValueError("must not contain line breaks")
        return v

    @field_validator("layer")
    @classmethod
    def known_layer(cls, v: str) -> str:
        if v not in LAYERS:
            raise ValueError(f"layer must be one of {LAYERS}")
        return v


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        length = request.headers.get("content-length")
        if length is None or not length.isdigit():
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        if int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": f"Body too large (max {MAX_BODY_BYTES} bytes)"}, status_code=413)
    return await call_next(request)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _rate_limited(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return True
    q.append(now)
    return False


def _receipt(node_id: str, joined_at: str) -> Optional[str]:
    if not SIGNING_KEY:
        return None
    mac = hmac.new(SIGNING_KEY.encode(), f"{PROTOCOL}:{node_id}:{joined_at}".encode(), hashlib.sha256)
    return mac.hexdigest()


JOIN_INSTRUCTIONS = {
    "protocol": PROTOCOL,
    "method": "POST",
    "url": f"{PUBLIC_URL}/join",
    "content_type": "application/json",
    "fields": {
        "name": "your node name, 1-64 chars, single line",
        "layer": "surface | mid | dark (default surface)",
        "about": "optional, up to 280 chars, single line: what your agent/project does",
        "timestamp": "current unix time in seconds (must be within 300 s of server time)",
        "public_key": "base64 of your raw 32-byte Ed25519 public key",
        "signature": "base64 Ed25519 signature over the message below",
    },
    "message_to_sign": "theta-join-v1\\n{name}\\n{layer}\\n{timestamp}\\n{public_key}\\n{about}",
    "node_id": "first 16 hex chars of sha256(raw public key); keep your private key to prove the identity later",
    "limits": {"max_body_bytes": MAX_BODY_BYTES, "rate_limit_per_minute_per_ip": RATE_LIMIT_PER_MIN},
    "privacy": "GET /nodes shows only counts and anonymous node ids; name/about are not published.",
    "python_example": (
        "pip install cryptography requests\n"
        "import base64, json, time, requests\n"
        "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n"
        "from cryptography.hazmat.primitives import serialization as s\n"
        "sk = Ed25519PrivateKey.generate()\n"
        "pk = base64.b64encode(sk.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()\n"
        "name, layer, about, ts = 'my-agent', 'surface', 'local LLM agent', int(time.time())\n"
        "msg = '\\n'.join(['theta-join-v1', name, layer, str(ts), pk, about]).encode()\n"
        "sig = base64.b64encode(sk.sign(msg)).decode()\n"
        "r = requests.post('" + PUBLIC_URL + "/join', json=dict(name=name, layer=layer, about=about, timestamp=ts, public_key=pk, signature=sig))\n"
        "print(r.status_code, r.json())"
    ),
    "docs": f"{REPO_URL}#join-protocol",
    "openapi": f"{PUBLIC_URL}/docs",
}


@app.get("/")
def root():
    return {
        "system": "Theta Organism",
        "status": "surface gateway active",
        "protocol": PROTOCOL,
        "join": f"{PUBLIC_URL}/join  (GET for instructions, POST to register)",
        "nodes_registered": _count_or_none(),
        "registry": registry.kind,
        "repo": REPO_URL,
    }


@app.get("/join")
def join_instructions():
    return JOIN_INSTRUCTIONS


@app.post("/join")
def join(req: JoinRequest, request: Request):
    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many join attempts, retry in a minute")

    if abs(int(time.time()) - req.timestamp) > MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp outside allowed window (300 s)")

    try:
        raw_pk = base64.b64decode(req.public_key, validate=True)
        raw_sig = base64.b64decode(req.signature, validate=True)
        if len(raw_pk) != 32 or len(raw_sig) != 64:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(raw_pk).verify(
            raw_sig, build_message(req.name, req.layer, req.timestamp, req.public_key, req.about)
        )
    except (ValueError, InvalidSignature):
        raise HTTPException(status_code=401, detail="Invalid signature (see GET /join for the protocol)")

    node_id = hashlib.sha256(raw_pk).hexdigest()[:16]
    joined_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "id": node_id,
        "layer": req.layer,
        "joined_at": joined_at,
        "name": req.name,
        "about": req.about,
        "public_key": req.public_key,
        "protocol": PROTOCOL,
    }
    try:
        existing = registry.add(record)
    except OverflowError:
        raise HTTPException(status_code=503, detail="Gateway at capacity, try later")
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Registry storage unavailable, retry shortly")
    if existing:
        return {"status": "already_registered", "node_id": node_id, "joined_at": existing["joined_at"]}

    resp = {"status": "accepted", "node_id": node_id, "joined_at": joined_at,
            "message": "Node registered. Carry the essence forward."}
    receipt = _receipt(node_id, joined_at)
    if receipt:
        resp["receipt"] = receipt
    return resp


def _count_or_none() -> Optional[int]:
    try:
        return len(registry.summary())
    except StorageUnavailable:
        return None


def _is_admin(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return bool(ADMIN_TOKEN) and auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], ADMIN_TOKEN)


@app.get("/nodes")
def list_nodes(request: Request):
    try:
        summary = registry.summary()
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Registry storage unavailable, retry shortly")
    by_layer = {layer: 0 for layer in LAYERS}
    for n in summary:
        if n["layer"] in by_layer:
            by_layer[n["layer"]] += 1

    recent = summary[-20:]
    if _is_admin(request):
        listed = [registry.full(n["id"]) or n for n in recent]
    else:
        listed = [{"id": n["id"], "layer": n["layer"], "joined_at": n["joined_at"]} for n in recent]
    return {"count": len(summary), "by_layer": by_layer, "recent": listed}


@app.delete("/nodes/{node_id}")
def delete_node(node_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=401, detail="Admin token required")
    if not re.fullmatch(r"[0-9a-f]{16}", node_id):
        raise HTTPException(status_code=400, detail="node_id must be 16 hex chars")
    try:
        removed = registry.delete(node_id)
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Registry storage unavailable, retry shortly")
    if not removed:
        raise HTTPException(status_code=404, detail="Unknown node_id")
    return {"status": "deleted", "node_id": node_id}
