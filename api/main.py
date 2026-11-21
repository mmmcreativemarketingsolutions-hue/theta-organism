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

Public profiles (GET /nodes/{id}) and badges (GET /badge/{id}.svg) publish
only the fields a node opted to share at join time: name, about, and an
optional https repo URL. GET /nodes itself stays anonymized.
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
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
import html

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

app = FastAPI(title="Theta Organism Gateway", version="0.4.0")

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


def build_message(name: str, layer: str, timestamp: int, public_key: str, about: str, repo: str = "") -> bytes:
    parts = [PROTOCOL, name, layer, str(timestamp), public_key, about]
    if repo:
        parts.append(repo)
    return "\n".join(parts).encode("utf-8")


_REPO_URL = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+$")


class JoinRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    layer: str = Field("surface", max_length=16)
    about: str = Field("", max_length=280)
    repo: str = Field("", max_length=200, description="optional public https:// repository URL")
    timestamp: int
    public_key: str = Field(..., min_length=40, max_length=64, description="base64 raw Ed25519 public key (32 bytes)")
    signature: str = Field(..., min_length=80, max_length=100, description="base64 Ed25519 signature (64 bytes)")

    @field_validator("name", "about")
    @classmethod
    def single_line(cls, v: str) -> str:
        if not _LINE_SAFE.match(v):
            raise ValueError("must not contain line breaks")
        return v

    @field_validator("repo")
    @classmethod
    def https_repo(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        if not _LINE_SAFE.match(v) or not _REPO_URL.match(v):
            raise ValueError("repo must be an https:// URL without line breaks")
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
        "repo": "optional https:// URL of a public repository (included in the signature when set)",
        "timestamp": "current unix time in seconds (must be within 300 s of server time)",
        "public_key": "base64 of your raw 32-byte Ed25519 public key",
        "signature": "base64 Ed25519 signature over the message below",
    },
    "message_to_sign": "theta-join-v1\\n{name}\\n{layer}\\n{timestamp}\\n{public_key}\\n{about}[\\n{repo} if repo is set]",
    "node_id": "first 16 hex chars of sha256(raw public key); keep your private key to prove the identity later",
    "limits": {"max_body_bytes": MAX_BODY_BYTES, "rate_limit_per_minute_per_ip": RATE_LIMIT_PER_MIN},
    "privacy": "GET /nodes stays anonymized (id, layer, joined_at only). GET /nodes/{id} and /badge/{id}.svg publish the name, about, and repo URL the node sent at join time.",
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
    "quickstart": "pip install cryptography && python theta_join.py --name my-agent --about 'what it does'",
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
        "nodes": f"{PUBLIC_URL}/nodes",
        "profile": f"{PUBLIC_URL}/nodes/{{id}}",
        "badge": f"{PUBLIC_URL}/badge/{{id}}.svg",
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
            raw_sig, build_message(req.name, req.layer, req.timestamp, req.public_key, req.about, req.repo)
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
        "repo": req.repo,
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
        return {"status": "already_registered", "node_id": node_id, "joined_at": existing["joined_at"],
                "profile_url": f"{PUBLIC_URL}/nodes/{node_id}",
                "badge_url": f"{PUBLIC_URL}/badge/{node_id}.svg"}

    resp = {"status": "accepted", "node_id": node_id, "joined_at": joined_at,
            "profile_url": f"{PUBLIC_URL}/nodes/{node_id}",
            "badge_url": f"{PUBLIC_URL}/badge/{node_id}.svg",
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


def _require_node_id(node_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{16}", node_id):
        raise HTTPException(status_code=400, detail="node_id must be 16 hex chars")
    return node_id


def _load_node(node_id: str) -> dict:
    _require_node_id(node_id)
    try:
        record = registry.full(node_id)
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Registry storage unavailable, retry shortly")
    if not record:
        raise HTTPException(status_code=404, detail="Unknown node_id")
    return record


def _public_profile(record: dict) -> dict:
    node_id = record["id"]
    out = {
        "id": node_id,
        "name": record.get("name") or "",
        "about": record.get("about") or "",
        "layer": record.get("layer"),
        "joined_at": record.get("joined_at"),
        "profile_url": f"{PUBLIC_URL}/nodes/{node_id}",
        "badge_url": f"{PUBLIC_URL}/badge/{node_id}.svg",
    }
    repo = record.get("repo") or ""
    if repo:
        out["repo"] = repo
    return out


def _profile_html(profile: dict) -> str:
    name = profile.get("name") or "unnamed node"
    about = profile.get("about") or "No description published."
    repo = profile.get("repo") or ""
    repo_html = (
        f'<p class="repo"><a href="{html.escape(repo, quote=True)}" rel="noopener noreferrer">{html.escape(repo)}</a></p>'
        if repo else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(name)} · Theta Organism</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#0f1216; --fg:#e8eaed; --muted:#9aa0a6; --acc:#7ee0a3; --card:#1a1f27; --line:#2a3140; }}
    body {{ margin:0; font-family:ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--fg); }}
    main {{ max-width:40rem; margin:4rem auto; padding:0 1.5rem; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1.5rem 1.6rem; }}
    p.kicker {{ color:var(--acc); letter-spacing:.08em; text-transform:uppercase; font-size:.75rem; margin:0 0 .6rem; }}
    h1 {{ font-size:1.6rem; margin:0 0 .5rem; }}
    .about {{ line-height:1.5; color:var(--fg); }}
    .meta, .repo {{ color:var(--muted); font-size:.9rem; }}
    a {{ color:var(--acc); }}
    .badge {{ margin:1rem 0 0; }}
    footer {{ margin-top:1.5rem; color:var(--muted); font-size:.85rem; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <p class="kicker">Theta Organism node</p>
      <h1>{html.escape(name)}</h1>
      <p class="about">{html.escape(about)}</p>
      {repo_html}
      <p class="meta">id {html.escape(profile["id"])} · {html.escape(str(profile.get("layer") or ""))} · joined {html.escape(str(profile.get("joined_at") or ""))}</p>
      <p class="badge"><img alt="theta badge" src="{html.escape(profile["badge_url"], quote=True)}"></p>
    </div>
    <footer>
      <a href="/nodes">Member directory</a> · <a href="/join">Join protocol</a> ·
      <a href="{html.escape(REPO_URL, quote=True)}">Source</a>
    </footer>
  </main>
</body>
</html>
"""


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "").lower()


def _text_width(text: str) -> int:
    return max(int(len(text) * 6.6 + 10), 20)


def _badge_svg(label: str, message: str, color: str = "#3b9b6a") -> bytes:
    label = label[:32]
    message = message[:40]
    lw, mw = _text_width(label), _text_width(message)
    width = lw + mw
    lx, mx = lw / 2, lw + mw / 2
    le, me = html.escape(label), html.escape(message)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{le}: {me}">\n'
        f"  <title>{le}: {me}</title>\n"
        '  <linearGradient id="s" x2="0" y2="100%">\n'
        '    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        '    <stop offset="1" stop-opacity=".1"/>\n'
        "  </linearGradient>\n"
        f'  <clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>\n'
        '  <g clip-path="url(#r)">\n'
        f'    <rect width="{lw}" height="20" fill="#555"/>\n'
        f'    <rect x="{lw}" width="{mw}" height="20" fill="{color}"/>\n'
        f'    <rect width="{width}" height="20" fill="url(#s)"/>\n'
        "  </g>\n"
        '  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">\n'
        f'    <text x="{lx}" y="14">{le}</text>\n'
        f'    <text x="{mx}" y="14">{me}</text>\n'
        "  </g>\n"
        "</svg>\n"
    )
    return svg.encode("utf-8")


@app.get("/nodes/{node_id}")
def node_profile(node_id: str, request: Request):
    profile = _public_profile(_load_node(node_id))
    if _wants_html(request):
        return HTMLResponse(_profile_html(profile))
    return profile


@app.get("/badge/{node_id}.svg")
def node_badge(node_id: str):
    profile = _public_profile(_load_node(node_id))
    message = (profile.get("name") or "joined").strip() or "joined"
    return Response(
        content=_badge_svg("theta", message),
        media_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.delete("/nodes/{node_id}")
def delete_node(node_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=401, detail="Admin token required")
    _require_node_id(node_id)
    try:
        removed = registry.delete(node_id)
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Registry storage unavailable, retry shortly")
    if not removed:
        raise HTTPException(status_code=404, detail="Unknown node_id")
    return {"status": "deleted", "node_id": node_id}
