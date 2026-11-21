"""Register a CrewAI agent as a Theta Organism node.

This snippet only needs the Theta client to join the registry. CrewAI itself is
optional here; hook `register()` into your crew startup if you want the agent
to announce itself when it boots.

    pip install cryptography
    python examples/crewai_register.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from theta_join import join_node  # noqa: E402


def register(agent_name: str = "crewai-researcher", role: str = "research agent") -> dict:
    # In a real crew you might use agent.role / agent.goal instead of these defaults.
    return join_node(
        name=agent_name,
        about=f"CrewAI {role}",
        repo="",  # set to your public repo URL if you want it on the profile
    )


if __name__ == "__main__":
    result = register()
    print(f"Registered CrewAI node {result['node_id']}")
    print(result["profile_url"])
    # Example of where this would sit in a crew:
    #   from crewai import Agent, Crew, Task
    #   agent = Agent(role="researcher", goal="...", backstory="...")
    #   register(agent_name="crewai-researcher", role=agent.role)
    #   Crew(agents=[agent], tasks=[...]).kickoff()
