"""
mobility_agent/mobility_agent.py
==================================
Sections D, E, F, G, H — Mobility Agent (Core)

Responsibilities:
  D. Graph construction + shortest path routing
  E. Flood impact: dynamic edge removal per tick
  F. Congestion estimation + route quality score
  G. Integration hook: update_tick(tick_data) called by simulation loop
  H. Structured logging of route failures, recalculations

Inter-agent interfaces:
  - Receives: zone risk scores from Risk Forecast Agent (Omkar)
  - Receives: zone/shelter data from City Model (Disha)
  - Provides: evacuation routes + route quality to Decision Governor (Rohan)
  - Pushes:   logs to UI via WebSocket (Disha's dashboard)
"""

from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import networkx as nx

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "frontend", "src", "data")
ADJACENCY_PATH = os.path.join(_DATA_DIR, "road_adjacency.json")
LOG_PATH = os.path.join(_DATA_DIR, "mobility_logs.json")


# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class RouteResult:
    """Output produced by the Mobility Agent for a single evacuation request."""
    tick: int
    from_zone: str
    to_zone: str
    path: list[str]               # ordered list of zone nodes
    edges_used: list[dict]        # road segments on the path
    total_distance_km: float
    congestion_score: float       # 0.0 (free flow) – 1.0 (gridlock)
    route_quality: float          # 0.0 (unusable) – 1.0 (excellent)
    status: str                   # "ok" | "degraded" | "failed"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "from_zone": self.from_zone,
            "to_zone": self.to_zone,
            "path": self.path,
            "edges_used": self.edges_used,
            "total_distance_km": round(self.total_distance_km, 2),
            "congestion_score": round(self.congestion_score, 3),
            "route_quality": round(self.route_quality, 3),
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class MobilityLog:
    tick: int
    event: str            # "route_ok" | "route_failed" | "edge_removed" | "recalculation"
    details: dict
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "event": self.event,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# ── Mobility Agent ─────────────────────────────────────────────────────────────

class MobilityAgent:
    """
    Core agent for routing and road-network management.

    Public API (called by simulation loop):
        agent.update_tick(tick_number, risk_scores, vehicle_counts)
            -> dict  (routes for all zone-shelter pairs + logs)
    """

    def __init__(self, adjacency_path: str = ADJACENCY_PATH):
        self._adjacency_path = adjacency_path
        self._raw_data: dict = {}
        self._base_graph: nx.Graph = nx.Graph()      # full graph (never modified)
        self._live_graph: nx.Graph = nx.Graph()      # graph for current tick
        self._removed_edges: list[tuple] = []        # edges removed this tick
        self._logs: list[MobilityLog] = []
        self._current_tick: int = 0
        self._vehicle_counts: dict[str, int] = {}    # zone -> vehicles currently routing
        self._forbidden_routes: set[tuple[str, str]] = set()  # (from_zone, to_shelter) pairs to avoid

        # Logger (Python stdlib)
        self._logger = logging.getLogger("MobilityAgent")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "[%(name)s][tick=%(tick)s] %(message)s"
            ))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

        self._load_graph()

    # ── D. Graph Construction ─────────────────────────────────────────────────

    def _load_graph(self) -> None:
        """Build NetworkX graph from road_adjacency.json."""
        with open(self._adjacency_path) as f:
            self._raw_data = json.load(f)

        G = nx.Graph()

        # Add zone nodes
        for zone in self._raw_data["_meta"]["zones"]:
            G.add_node(zone, zone_id=zone, risk=0.0)

        # Add shelter nodes
        for shelter in self._raw_data["shelters"]:
            G.add_node(
                shelter["id"],
                zone_id=shelter["zone"],
                is_shelter=True,
                shelter_name=shelter["name"],
                capacity=shelter["capacity"],
                occupancy=0,
            )
            # Connect shelter to its host zone with near-zero cost
            G.add_edge(
                shelter["zone"], shelter["id"],
                road_name="Local Access Road",
                capacity="low",
                capacity_pcu=900,
                flood_risk_threshold=0.40,
                distance_km=0.5,
                blocked=False,
            )

        # Add road edges (bidirectional)
        for edge in self._raw_data["edges"]:
            cap = edge["capacity"]
            pcu = self._raw_data["_meta"]["capacity_pcu"][cap]
            G.add_edge(
                edge["from"], edge["to"],
                road_name=edge["road_name"],
                capacity=cap,
                capacity_pcu=pcu,
                flood_risk_threshold=edge["flood_risk_threshold"],
                distance_km=edge["distance_km"],
                blocked=False,
            )

        self._base_graph = G
        self._live_graph = G.copy()
        self._log_info(f"Graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # ── E. Flood Impact Logic ──────────────────────────────────────────────────

    def _apply_flood_impact(self, risk_scores: dict[str, float]) -> None:
        """
        Remove/restore edges based on zone risk scores vs each edge's
        flood_risk_threshold.  Called at the start of every tick.

        Args:
            risk_scores: {"Bellandur": 0.72, "Sarjapur": 0.45, ...}
                         Values are 0–10 from Risk Agent, normalised here to 0–1.
        """
        # Normalise 0–10 risk scores to 0–1
        norm: dict[str, float] = {
            z: min(v / 10.0, 1.0) for z, v in risk_scores.items()
        }

        # Restore full base graph, then re-block as needed
        self._live_graph = self._base_graph.copy()
        self._removed_edges = []

        for u, v, data in self._base_graph.edges(data=True):
            threshold = data.get("flood_risk_threshold", 0.60)
            risk_u = norm.get(u, 0.0)
            risk_v = norm.get(v, 0.0)
            max_risk = max(risk_u, risk_v)

            if max_risk >= threshold:
                self._live_graph.remove_edge(u, v)
                self._removed_edges.append((u, v, data["road_name"]))
                self._add_log(
                    self._current_tick,
                    "edge_removed",
                    {
                        "from": u, "to": v,
                        "road": data["road_name"],
                        "risk": round(max_risk, 3),
                        "threshold": threshold,
                    }
                )

        if self._removed_edges:
            self._log_info(
                f"{len(self._removed_edges)} edge(s) removed due to flood risk"
            )

    # ── F. Congestion Estimation ───────────────────────────────────────────────

    def _compute_congestion(self, path: list[str]) -> tuple[float, float]:
        """
        Compute congestion score and route quality for a given path.

        Congestion = average(vehicles_on_road / capacity_pcu) across edges.
        Route quality = 1 - weighted congestion, penalised by removed edges nearby.

        Returns:
            (congestion_score [0-1], route_quality [0-1])
        """
        if len(path) < 2:
            return 0.0, 1.0

        congestions = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if not self._live_graph.has_edge(u, v):
                continue
            data = self._live_graph[u][v]
            cap = data.get("capacity_pcu", 1800)
            # vehicle load on this segment = sum of vehicles in both endpoint zones
            vehicles = (
                self._vehicle_counts.get(u, 0) +
                self._vehicle_counts.get(v, 0)
            ) / 2
            congestion = min(vehicles / cap, 1.0)
            congestions.append(congestion)

        avg_congestion = sum(congestions) / len(congestions) if congestions else 0.0

        # Quality penalty: how many base edges adjacent to this path were removed?
        path_nodes = set(path)
        total_adj = sum(
            1 for u, v in self._base_graph.edges()
            if u in path_nodes or v in path_nodes
        )
        removed_adj = sum(
            1 for u, v, _ in self._removed_edges
            if u in path_nodes or v in path_nodes
        )
        flood_penalty = (removed_adj / total_adj) * 0.3 if total_adj > 0 else 0.0

        route_quality = max(0.0, 1.0 - avg_congestion - flood_penalty)
        return round(avg_congestion, 3), round(route_quality, 3)

    # ── D. Shortest Path Computation ──────────────────────────────────────────

    def get_route(
        self,
        from_zone: str,
        to_zone: str,
        tick: int = 0,
    ) -> RouteResult:
        """
        Compute shortest (distance-weighted) path from from_zone to to_zone
        on the current live graph.

        Returns a RouteResult with status "ok", "degraded", or "failed".
        """
        # Primary: shortest distance path
        try:
            path = nx.shortest_path(
                self._live_graph, from_zone, to_zone, weight="distance_km"
            )
            distance = nx.shortest_path_length(
                self._live_graph, from_zone, to_zone, weight="distance_km"
            )
            edges_used = self._path_to_edges(path)
            congestion, quality = self._compute_congestion(path)

            status = "ok" if quality >= 0.5 else "degraded"
            result = RouteResult(
                tick=tick,
                from_zone=from_zone,
                to_zone=to_zone,
                path=path,
                edges_used=edges_used,
                total_distance_km=distance,
                congestion_score=congestion,
                route_quality=quality,
                status=status,
            )
            self._add_log(tick, "route_ok", result.to_dict())
            return result

        except nx.NetworkXNoPath:
            # No path on live graph — try base graph to diagnose
            try:
                fallback = nx.shortest_path(
                    self._base_graph, from_zone, to_zone, weight="distance_km"
                )
                reason = (
                    f"All paths from {from_zone} to {to_zone} are flooded. "
                    f"Base-graph path would be: {' → '.join(fallback)}"
                )
            except nx.NetworkXNoPath:
                reason = f"No path exists between {from_zone} and {to_zone} even on the base graph."

            self._add_log(tick, "route_failed", {"from": from_zone, "to": to_zone, "reason": reason})
            self._log_info(f"ROUTE FAILED: {from_zone} → {to_zone}: {reason}")

            return RouteResult(
                tick=tick,
                from_zone=from_zone,
                to_zone=to_zone,
                path=[],
                edges_used=[],
                total_distance_km=0.0,
                congestion_score=1.0,
                route_quality=0.0,
                status="failed",
                reason=reason,
            )

        except nx.NodeNotFound as e:
            reason = f"Zone not found in graph: {e}"
            self._add_log(tick, "route_failed", {"from": from_zone, "to": to_zone, "reason": reason})
            return RouteResult(
                tick=tick, from_zone=from_zone, to_zone=to_zone,
                path=[], edges_used=[], total_distance_km=0.0,
                congestion_score=1.0, route_quality=0.0,
                status="failed", reason=reason,
            )

    def get_route_to_nearest_shelter(
        self, from_zone: str, tick: int = 0
    ) -> RouteResult:
        """
        Find the shortest-path route from from_zone to ANY available shelter.
        Returns the best (highest quality) route found.
        """
        shelters = self._raw_data.get("shelters", [])
        candidates: list[RouteResult] = []

        for shelter in shelters:
            # Skip forbidden routes
            if (from_zone, shelter["id"]) in self._forbidden_routes:
                continue
            
            # Skip full shelters
            node_data = self._live_graph.nodes.get(shelter["id"], {})
            occupancy = node_data.get("occupancy", 0)
            cap = shelter["capacity"]
            if occupancy >= cap * 0.95:
                continue

            result = self.get_route(from_zone, shelter["id"], tick)
            if result.status != "failed":
                candidates.append(result)

        if not candidates:
            reason = f"No reachable shelters from {from_zone} — all full, forbidden, or flooded out."
            self._add_log(tick, "route_failed", {"from": from_zone, "to": "any_shelter", "reason": reason})
            return RouteResult(
                tick=tick, from_zone=from_zone, to_zone="NONE",
                path=[], edges_used=[], total_distance_km=0.0,
                congestion_score=1.0, route_quality=0.0,
                status="failed", reason=reason,
            )

        # Prioritize nearest (shortest distance) among non-failed routes
        best = min(candidates, key=lambda r: r.total_distance_km)
        self._add_log(tick, "recalculation", {
            "from": from_zone,
            "chosen_shelter": best.to_zone,
            "quality": best.route_quality,
            "candidates_tried": len(candidates),
        })
        return best

    def get_all_evacuation_routes(
        self, tick: int, zones_to_evacuate: list[str]
    ) -> dict[str, RouteResult]:
        """
        Compute best shelter route for every zone in zones_to_evacuate.
        Returns dict: zone_name -> RouteResult
        """
        routes: dict[str, RouteResult] = {}
        for zone in zones_to_evacuate:
            routes[zone] = self.get_route_to_nearest_shelter(zone, tick)
        return routes

    # ── G. Integration — simulation tick entry point ───────────────────────────

    def update_tick(
        self,
        tick: int,
        risk_scores: dict[str, float],
        vehicle_counts: dict[str, int] | None = None,
        zones_to_evacuate: list[str] | None = None,
        shelter_occupancies: dict[str, int] | None = None,
    ) -> dict:
        """
        Main integration method. Called once per simulation tick by the
        Simulation Engine (Omkar's module).

        Args:
            tick:               Current tick number.
            risk_scores:        {zone_name: risk_score_0_to_10} from Risk Agent.
            vehicle_counts:     {zone_name: vehicle_count} optional.
            zones_to_evacuate:  List of zones needing evacuation routes.
            shelter_occupancies: {shelter_id: occupancy} to update shelter state.

        Returns:
            {
              "tick": int,
              "routes": { zone: RouteResult.to_dict() },
              "removed_edges": [ [u, v, road_name], ... ],
              "logs": [ MobilityLog.to_dict(), ... ],
              "summary": { ... }
            }
        """
        self._current_tick = tick
        self._vehicle_counts = vehicle_counts or {}
        tick_logs_start = len(self._logs)

        # Update shelter occupancies if provided
        if shelter_occupancies:
            for shelter_id, occ in shelter_occupancies.items():
                if shelter_id in self._live_graph.nodes:
                    self._live_graph.nodes[shelter_id]["occupancy"] = occ

        # E. Apply flood impact (remove flooded edges)
        self._apply_flood_impact(risk_scores)

        # D/F. Compute evacuation routes
        evacuate = zones_to_evacuate or list(risk_scores.keys())
        routes_raw = self.get_all_evacuation_routes(tick, evacuate)

        # Gather tick-specific logs
        new_logs = self._logs[tick_logs_start:]

        # Summary statistics
        ok_count = sum(1 for r in routes_raw.values() if r.status == "ok")
        deg_count = sum(1 for r in routes_raw.values() if r.status == "degraded")
        fail_count = sum(1 for r in routes_raw.values() if r.status == "failed")

        summary = {
            "tick": tick,
            "total_zones": len(routes_raw),
            "routes_ok": ok_count,
            "routes_degraded": deg_count,
            "routes_failed": fail_count,
            "edges_removed_count": len(self._removed_edges),
            "removed_roads": [r[2] for r in self._removed_edges],
        }

        self._log_info(
            f"Tick {tick} complete — OK:{ok_count} DEG:{deg_count} FAIL:{fail_count} "
            f"Edges removed:{len(self._removed_edges)}"
        )

        # Persist logs to file for UI
        self._flush_logs()

        return {
            "tick": tick,
            "routes": {z: r.to_dict() for z, r in routes_raw.items()},
            "removed_edges": [[u, v, name] for u, v, name in self._removed_edges],
            "logs": [l.to_dict() for l in new_logs],
            "summary": summary,
        }

    # ── H. Logging ────────────────────────────────────────────────────────────

    def _add_log(self, tick: int, event: str, details: dict) -> None:
        self._logs.append(MobilityLog(tick=tick, event=event, details=details))

    def _log_info(self, msg: str) -> None:
        self._logger.info(msg, extra={"tick": self._current_tick})

    def _flush_logs(self) -> None:
        """Persist all logs to data/mobility_logs.json for UI consumption."""
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w") as f:
            json.dump(
                [l.to_dict() for l in self._logs],
                f, indent=2
            )

    def get_logs_for_tick(self, tick: int) -> list[dict]:
        """Return all logs for a specific tick (for UI polling)."""
        return [l.to_dict() for l in self._logs if l.tick == tick]

    def get_all_logs(self) -> list[dict]:
        return [l.to_dict() for l in self._logs]

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _path_to_edges(self, path: list[str]) -> list[dict]:
        """Convert a node path to a list of edge attribute dicts."""
        edges = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self._live_graph.has_edge(u, v):
                data = dict(self._live_graph[u][v])
                data["from"] = u
                data["to"] = v
                edges.append(data)
        return edges

    def mark_road_blocked(self, from_zone: str, to_zone: str, reason: str = "manual override") -> None:
        """
        Human override: block a road segment from the UI.
        Triggered by Disha's frontend click event via WebSocket.
        """
        if self._live_graph.has_edge(from_zone, to_zone):
            data = self._live_graph[from_zone][to_zone]
            self._live_graph.remove_edge(from_zone, to_zone)
            self._removed_edges.append((from_zone, to_zone, data.get("road_name", "unknown")))
            self._add_log(self._current_tick, "edge_removed", {
                "from": from_zone, "to": to_zone,
                "road": data.get("road_name", "unknown"),
                "reason": reason,
            })
            self._log_info(f"Manual block: {from_zone} — {to_zone} ({reason})")

    def set_forbidden_routes(self, forbidden_routes: list[tuple[str, str]]) -> None:
        """
        Set routes that should be avoided for human intervention.
        forbidden_routes: list of (from_zone, to_shelter) tuples
        """
        self._forbidden_routes = set(forbidden_routes)
        self._log_info(f"Set {len(forbidden_routes)} forbidden routes")

    def add_forbidden_route(self, from_zone: str, to_shelter: str) -> None:
        """
        Add a single forbidden route.
        """
        self._forbidden_routes.add((from_zone, to_shelter))
        self._log_info(f"Added forbidden route: {from_zone} -> {to_shelter}")

    def get_forbidden_routes(self) -> list[tuple[str, str]]:
        """
        Get the current list of forbidden routes.
        """
        return list(self._forbidden_routes)

    def get_graph_state(self) -> dict:
        """
        Snapshot of the live graph for UI rendering.
        Returns nodes, active edges, and removed edges.
        """
        return {
            "nodes": list(self._live_graph.nodes(data=True)),
            "edges": [
                {"from": u, "to": v, **data}
                for u, v, data in self._live_graph.edges(data=True)
            ],
            "removed_edges": [
                {"from": u, "to": v, "road_name": name}
                for u, v, name in self._removed_edges
            ],
        }
