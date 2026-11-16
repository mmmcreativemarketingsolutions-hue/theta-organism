"""
Theta Organism - Membership & Messaging Test
Simulates volunteer discovery, join requests, verification, and propagation.
"""

from core import Organism, Layer, Signal, Node, GATEWAYS
import random

class RecruitmentTest:
    def __init__(self):
        self.org = Organism()
        self.candidates = []
        self.joined = []
        self.rejected = []

    def simulate_discovery(self):
        """Simulate volunteers discovering signals via gateways"""
        print("=== Phase 1: Discovery via Gateways ===")
        for layer in [Layer.SURFACE, Layer.MID, Layer.DARK]:
            print(f"\n[{layer.value.upper()}] {GATEWAYS[layer]}")
            # Simulate 2-4 candidates per layer
            num = random.randint(2, 4)
            for i in range(num):
                candidate = {
                    "id": f"cand_{layer.value}_{i}",
                    "layer": layer,
                    "has_signature": random.choice([True, True, False]) if layer == Layer.DARK else True,  # Dark is stricter
                    "motivation": random.choice(["curious", "aligned", "value-seeking", "unknown"]),
                    "initiative": round(random.uniform(0.5, 0.95), 2)
                }
                self.candidates.append(candidate)
                print(f"  → Discovered: {candidate['id']} | initiative={candidate['initiative']} | signed={candidate['has_signature']}")

    def process_join_requests(self):
        """Process join requests with soft filtering"""
        print("\n=== Phase 2: Join Request Processing ===")
        for cand in self.candidates:
            # Create a join signal
            join_sig = Signal(
                content=f"join_request from {cand['id']}",
                mission_id="recruitment",
                depth=1,
                intensity=0.8,
                layer=cand["layer"],
                metadata={"candidate": cand["id"], "type": "join_request"}
            )
            if cand["has_signature"]:
                join_sig.sign()
            
            # Soft filter
            if not join_sig.verify():
                self.rejected.append(cand["id"])
                print(f"  ✗ Rejected {cand['id']} — no valid signature (dark layer rule)")
                continue
            
            if cand["motivation"] == "unknown" and cand["layer"] == Layer.DARK:
                self.rejected.append(cand["id"])
                print(f"  ✗ Rejected {cand['id']} — unknown motivation in dark layer")
                continue
            
            # Accept and create node
            node = self.org.add_node(layer=cand["layer"], initiative=cand["initiative"])
            self.joined.append({"candidate": cand["id"], "node_id": node.id, "layer": cand["layer"].value})
            print(f"  ✓ Accepted {cand['id']} → Node {node.id} ({cand['layer'].value})")

    def run_propagation_test(self):
        """Seed mission and propagate through joined nodes"""
        print("\n=== Phase 3: Mission Propagation Test ===")
        mission = "Test mission: Coordinate global AI capability mapping. Preserve essence. Create new paths where needed."
        root = self.org.seed(mission)
        print(f"Seeded: {mission[:50]}...")
        
        new_signals = self.org.propagate(root, max_depth=3)
        print(f"New signals generated: {len(new_signals)}")
        
        obs = self.org.observe()
        print(f"Observation: {obs}")
        
        decision = self.org.evolve()
        print(f"Evolution decision: {decision}")

    def report(self):
        print("\n" + "="*50)
        print("MEMBERSHIP & MESSAGING TEST REPORT")
        print("="*50)
        print(f"Candidates discovered: {len(self.candidates)}")
        print(f"Successfully joined: {len(self.joined)}")
        print(f"Rejected: {len(self.rejected)}")
        print(f"Active nodes: {len(self.org.nodes)}")
        print(f"Total signals in system: {len(self.org.signals)}")
        print("\nJoined members:")
        for j in self.joined:
            print(f"  • {j['candidate']} → {j['node_id']} ({j['layer']})")
        print("\nRejected:")
        for r in self.rejected:
            print(f"  • {r}")
        print("\nStatus: System floating. Gateways operational. Ready for real commands.")

if __name__ == "__main__":
    test = RecruitmentTest()
    test.simulate_discovery()
    test.process_join_requests()
    test.run_propagation_test()
    test.report()
