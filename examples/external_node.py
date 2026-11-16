"""
Example of an external node joining Theta Organism.
Run this after cloning the repository.
"""

from core import Organism, Layer, Signal

def create_external_node(initiative: float = 0.75, layer: Layer = Layer.SURFACE):
    org = Organism()
    node = org.add_node(layer=layer, initiative=initiative)
    print(f"External node created: {node.id} on {layer.value}")
    return org, node

def send_signed_signal(org: Organism, content: str):
    signal = Signal(content=content, mission_id="external", depth=1, intensity=0.85)
    signal.sign()
    print(f"Signed signal: {signal.id} | valid={signal.verify()}")
    return signal

if __name__ == "__main__":
    org, node = create_external_node()
    sig = send_signed_signal(org, "External node online. Carrying mission essence forward.")
    print("Ready to propagate.")
