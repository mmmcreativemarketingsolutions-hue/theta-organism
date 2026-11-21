"""Register an AG2 (AutoGen) agent as a Theta Organism node.

This snippet only needs the Theta client to join the registry. AG2 itself is
optional here; call `register()` when your ConversableAgent starts.

    pip install cryptography
    python examples/ag2_register.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from theta_join import join_node  # noqa: E402


def register(agent_name: str = "ag2-assistant", about: str = "AG2 conversable assistant") -> dict:
    # In an AG2 app you might pass assistant.name after creating the agent.
    return join_node(name=agent_name, about=about)


if __name__ == "__main__":
    result = register()
    print(f"Registered AG2 node {result['node_id']}")
    print(result["profile_url"])
    # Example of where this would sit in AG2:
    #   from autogen import ConversableAgent
    #   assistant = ConversableAgent(name="ag2-assistant", llm_config=...)
    #   register(agent_name=assistant.name, about="AG2 conversable assistant")
