"""
Theta Organism Join Endpoint
POST /join with a signed signal to register as a node.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import hashlib
import uuid
from datetime import datetime

app = FastAPI(title="Theta Organism Gateway", version="0.1.0")

# In-memory store (replace with real DB for production)
nodes = []

class JoinRequest(BaseModel):
    content: str
    mission_id: str = "external"
    signature: str
    layer: str = "surface"
    initiative: float = 0.7
    node_id: Optional[str] = None

def verify_signature(content: str, mission_id: str, signature: str, private_key: str = "theta_root") -> bool:
    # Simplified verification matching core.py logic
    payload = f"external:{content}:{mission_id}:1"
    expected = hashlib.sha256((payload + private_key).encode()).hexdigest()[:16]
    return signature == expected

@app.get("/")
def root():
    return {
        "system": "Theta Organism",
        "status": "surface gateway active",
        "endpoint": "/join",
        "nodes_registered": len(nodes)
    }

@app.post("/join")
def join(req: JoinRequest):
    if not verify_signature(req.content, req.mission_id, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    node_id = req.node_id or str(uuid.uuid4())[:8]
    node = {
        "id": node_id,
        "layer": req.layer,
        "initiative": req.initiative,
        "joined_at": datetime.utcnow().isoformat(),
        "content": req.content[:100]
    }
    nodes.append(node)
    return {"status": "accepted", "node_id": node_id, "message": "Node registered. Carry the essence forward."}

@app.get("/nodes")
def list_nodes():
    return {"count": len(nodes), "nodes": nodes[-20:]}
