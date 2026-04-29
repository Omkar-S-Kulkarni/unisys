"""
mobility_agent/simulation_integration.py
==========================================
Section G — Integration with Simulation Loop

This is the entry point that Omkar's Simulation Engine calls
every tick. It wires together:
  - MobilityAgent      (this module)
  - Risk scores        (from Risk Forecast Agent — Omkar)
  - City Model         (from City Model — Disha)
  - WebSocket bridge   (to Disha's frontend)
  - Decision Governor  (Rohan's module consumes the return value)

Expected call from simulation_engine.py:
    from mobility_agent.simulation_integration import MobilityIntegration
    mob = MobilityIntegration()
    result = mob.on_tick(tick, simulation_state)
"""

from __future__ import annotations

import json
import os
from typing import Any

from agents.mobility_agent.mobility_agent import MobilityAgent
from agents.mobility_agent.websocket_bridge import MobilityBridge

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DATA_DIR = os.path.join(ROOT_DIR, "frontend", "src", "data")


class MobilityIntegration:
    """
    Adapter layer consumed by the Simulation Engine each tick.

    Input (simulation_state dict, keys expected from other agents):
        simulation_state = {
            "tick": int,
            "zone_risk_scores": {zone: float 0-10},       # from Risk Agent (Omkar)
            "vehicle_counts":   {zone: int},               # optional
            "shelter_occupancies": {shelter_id: int},      # from City Model (Disha)
            "zones_to_evacuate": [str],                    # from Decision Governor (Rohan)
        }

    Output (returned to simulation loop / Decision Governor):
        {
            "tick": int,
            "routes": { zone: RouteResult dict },
            "removed_edges": [ [u, v, road_name], ... ],
            "logs": [ MobilityLog dict, ... ],
            "summary": { ... },
        }
    """

    def __init__(
        self,
        adjacency_path: str | None = None,
        ws_url: str = "ws://localhost:8765",
    ):
        adj = adjacency_path or os.path.join(_DATA_DIR, "road_adjacency.json")
        self.agent = MobilityAgent(adjacency_path=adj)
        self.bridge = MobilityBridge(ws_url=ws_url)

    def on_tick(self, tick: int, simulation_state: dict) -> dict:
        """
        Called once per simulation tick.
        Computes routes, applies flood logic, and pushes updates to UI.
        """
        risk_scores: dict[str, float] = simulation_state.get("zone_risk_scores", {})
        vehicle_counts: dict[str, int] = simulation_state.get("vehicle_counts", {})
        shelter_occupancies: dict[str, int] = simulation_state.get("shelter_occupancies", {})
        zones_to_evacuate: list[str] = simulation_state.get(
            "zones_to_evacuate", list(risk_scores.keys())
        )

        # Core tick update
        result = self.agent.update_tick(
            tick=tick,
            risk_scores=risk_scores,
            vehicle_counts=vehicle_counts,
            zones_to_evacuate=zones_to_evacuate,
            shelter_occupancies=shelter_occupancies,
        )

        # Push to frontend
        self.bridge.send_tick_update(result)

        # Also push graph topology for map re-render
        self.bridge.send_graph_state(self.agent.get_graph_state())

        return result

    def handle_manual_block(self, from_zone: str, to_zone: str) -> None:
        """
        Called when Disha's UI sends a 'block road' WebSocket message.
        Propagates the human override to the agent immediately.
        """
        self.agent.mark_road_blocked(from_zone, to_zone, reason="UI manual override")
        self.bridge.send_graph_state(self.agent.get_graph_state())

    def get_logs(self, tick: int | None = None) -> list[dict]:
        if tick is not None:
            return self.agent.get_logs_for_tick(tick)
        return self.agent.get_all_logs()
