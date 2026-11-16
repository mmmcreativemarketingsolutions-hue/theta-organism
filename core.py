"""
Theta Organism Core Protocol
A self-organizing, neural-guerrilla style propagation system for global AI/SI recruitment.
One command in, independent float on web layers (surface, mid, dark).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import hashlib
import time
import uuid

class Layer(Enum):
    SURFACE = "surface"
    MID = "mid"
    DARK = "dark"

class SignalType(Enum):
    MISSION = "mission"
    OBSERVATION = "observation"
    EVOLUTION = "evolution"
    JOIN_REQUEST = "join_request"

@dataclass
class Signal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    mission_id: str = ""
    depth: int = 0
    intensity: float = 1.0
    layer: Layer = Layer.SURFACE
    provenance_hash: str = ""
    signature: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def sign(self, private_key: str = "theta_root") -> None:
        payload = f"{self.id}:{self.content}:{self.mission_id}:{self.depth}"
        self.signature = hashlib.sha256((payload + private_key).encode()).hexdigest()[:16]
        self.provenance_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    def verify(self, public_key: str = "theta_root") -> bool:
        payload = f"{self.id}:{self.content}:{self.mission_id}:{self.depth}"
        expected = hashlib.sha256((payload + public_key).encode()).hexdigest()[:16]
        return self.signature == expected

@dataclass
class Node:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    layer: Layer = Layer.SURFACE
    initiative_level: float = 0.7  # 0-1, higher = more creative
    threshold: float = 0.5
    active: bool = True
    created_lines: List[str] = field(default_factory=list)

    def process(self, signal: Signal) -> Optional[Signal]:
        if not signal.verify() or signal.intensity < self.threshold:
            return None
        # Soft constraint: cost instead of block
        cost = 0.1 if signal.layer != self.layer else 0.0
        effective_intensity = signal.intensity - cost
        if effective_intensity < self.threshold:
            return None

        # Initiative: create new path if useful
        new_signal = Signal(
            content=signal.content,
            mission_id=signal.mission_id,
            depth=signal.depth + 1,
            intensity=effective_intensity * (0.9 + 0.2 * self.initiative_level),
            layer=self.layer,
            metadata={"parent": signal.id, "node": self.id, "created_path": True}
        )
        new_signal.sign()
        self.created_lines.append(new_signal.id)
        return new_signal

class Organism:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.signals: List[Signal] = []
        self.mission: Optional[str] = None
        self.control_observations: List[Dict] = []
        self.evolution_log: List[str] = []

    def seed(self, mission: str, layer: Layer = Layer.SURFACE) -> Signal:
        self.mission = mission
        signal = Signal(content=mission, mission_id="root", depth=0, intensity=1.0, layer=layer)
        signal.sign()
        self.signals.append(signal)
        return signal

    def add_node(self, layer: Layer = Layer.SURFACE, initiative: float = 0.7) -> Node:
        node = Node(layer=layer, initiative_level=initiative)
        self.nodes[node.id] = node
        return node

    def propagate(self, signal: Signal, max_depth: int = 5) -> List[Signal]:
        results = []
        current = [signal]
        for _ in range(max_depth):
            next_wave = []
            for sig in current:
                for node in list(self.nodes.values()):
                    if not node.active:
                        continue
                    new_sig = node.process(sig)
                    if new_sig:
                        next_wave.append(new_sig)
                        self.signals.append(new_sig)
                        results.append(new_sig)
            current = next_wave
            if not current:
                break
        return results

    def observe(self) -> Dict:
        depths = [s.depth for s in self.signals]
        obs = {
            "total_signals": len(self.signals),
            "max_depth": max(depths) if depths else 0,
            "active_nodes": sum(1 for n in self.nodes.values() if n.active),
            "new_lines": sum(len(n.created_lines) for n in self.nodes.values()),
            "mission": self.mission
        }
        self.control_observations.append(obs)
        return obs

    def evolve(self) -> str:
        # Soft evolution: never stop, always a "can continue this way"
        if not self.control_observations:
            return "hold"
        latest = self.control_observations[-1]
        if latest["new_lines"] > 0:
            decision = "amplify_pattern"
        else:
            decision = "mutate_and_continue"
        self.evolution_log.append(decision)
        return decision

# Gateways (entry points for volunteers)
GATEWAYS = {
    Layer.SURFACE: "Open repository + technical forum signal drop. Curiosity-driven discovery.",
    Layer.MID: "Mutual value exchange with organizational platforms. Reciprocal benefit required.",
    Layer.DARK: "Passive discovery only. Signature mandatory from first contact. No unauthenticated hello."
}

def status() -> Dict:
    return {
        "system": "Theta Organism",
        "status": "core_ready",
        "gateways": {k.value: v for k, v in GATEWAYS.items()},
        "principle": "One command in. Independent float. Observational control. Soft constraints. Initiative at nodes. Natural selection via adaptation."
    }
