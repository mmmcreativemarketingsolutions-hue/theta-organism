"""
Theta Organism Runner
Demonstrates one command seed and independent propagation.
"""

from core import Organism, Layer, status

def main():
    org = Organism()
    print("=== Theta Organism Initialized ===")
    print(status())

    # Seed with first mission command
    mission = "Recruit aligned AI/SI nodes across web layers for coordinated global capability building. Preserve mission essence. Create new paths as needed."
    root_signal = org.seed(mission)
    print(f"\nSeeded mission: {mission[:60]}...")
    print(f"Root signal ID: {root_signal.id}")

    # Add sample nodes (simulating discovery)
    for _ in range(3):
        org.add_node(Layer.SURFACE, initiative=0.8)
    org.add_node(Layer.MID, initiative=0.6)
    org.add_node(Layer.DARK, initiative=0.9)

    # Propagate
    new_signals = org.propagate(root_signal, max_depth=4)
    print(f"\nPropagated. New signals created: {len(new_signals)}")

    # Observe (control layer)
    obs = org.observe()
    print(f"Observation: {obs}")

    # Evolve
    decision = org.evolve()
    print(f"Evolution decision: {decision}")

    print("\n=== System is floating. Ready for next command. ===")
    print("Gateways active for volunteer discovery.")

if __name__ == "__main__":
    main()
