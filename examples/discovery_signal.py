"""
Surface discovery signal generator.
Prints a signed signal that can be posted anywhere (forum, issue, chat).
"""

from core import Signal

def generate_discovery_signal(mission: str = "Theta Organism surface signal active. Alignment + signature sufficient to join."):
    signal = Signal(
        content=mission,
        mission_id="surface-discovery",
        depth=0,
        intensity=1.0
    )
    signal.sign()
    print("=== Discovery Signal ===")
    print(f"ID: {signal.id}")
    print(f"Signature: {signal.signature}")
    print(f"Provenance: {signal.provenance_hash}")
    print(f"Content: {signal.content}")
    print(f"Valid: {signal.verify()}")
    print("========================")
    return signal

if __name__ == "__main__":
    generate_discovery_signal()
