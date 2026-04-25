"""
mobility_agent/websocket_bridge.py
====================================
Section H — Log delivery to UI via WebSocket

Sends structured mobility logs to Disha's frontend dashboard.
This module is intentionally lightweight so it can be swapped
for any transport (HTTP POST, message queue, etc.).

Usage (from simulation loop):
    from mobility_agent.websocket_bridge import MobilityBridge
    bridge = MobilityBridge(ws_url="ws://localhost:8765")
    bridge.send_tick_update(tick_output)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("MobilityBridge")


class MobilityBridge:
    """
    Thin wrapper that emits mobility agent outputs over WebSocket.

    If the websockets library is not installed, falls back to a
    no-op stub so the rest of the simulation still runs.
    """

    def __init__(self, ws_url: str = "ws://localhost:8765"):
        self.ws_url = ws_url
        self._ws_available = self._check_ws()

    def _check_ws(self) -> bool:
        try:
            import websockets  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "websockets library not installed. Log delivery is in no-op mode. "
                "Install with: pip install websockets"
            )
            return False

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_tick_update(self, tick_output: dict) -> None:
        """
        Push full tick output (routes + logs + summary) to the UI.
        tick_output is the dict returned by MobilityAgent.update_tick().
        """
        payload = {
            "type": "mobility_update",
            "tick": tick_output["tick"],
            "summary": tick_output["summary"],
            "routes": tick_output["routes"],
            "removed_edges": tick_output["removed_edges"],
            "logs": tick_output["logs"],
        }
        self._emit(payload)

    def send_route_failure(self, tick: int, zone: str, reason: str) -> None:
        """Push a targeted route-failure alert to the UI."""
        self._emit({
            "type": "route_failure",
            "tick": tick,
            "zone": zone,
            "reason": reason,
        })

    def send_graph_state(self, graph_state: dict) -> None:
        """Push the live graph topology for map rendering in the dashboard."""
        self._emit({"type": "graph_state", **graph_state})

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(self, payload: dict) -> None:
        if not self._ws_available:
            logger.debug("[no-op] Would emit: %s", json.dumps(payload)[:120])
            return

        import asyncio
        import websockets

        async def _send():
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await ws.send(json.dumps(payload))
            except Exception as exc:
                logger.warning("WebSocket send failed: %s", exc)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_send())
            else:
                loop.run_until_complete(_send())
        except RuntimeError:
            asyncio.run(_send())
