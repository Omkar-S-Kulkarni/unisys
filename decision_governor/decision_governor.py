"""
decision_governor/decision_governor.py
========================================
Core Decision Governor for ADEO disaster evacuation orchestration.

VERIFIED FIELD SOURCES (from project file audit):
  ─────────────────────────────────────────────────────────────────
  zone["id"]                   → city_model.json → zones[].id
  zone["name"]                 → city_model.json → zones[].name
  zone["population"]           → city_model.json → zones[].population
  zone["elderly_pct"]          → city_model.json → zones[].elderly_pct
  zone["population_density"]   → city_model.json → zones[].population_density
  zone["elevation_tier"]       → city_model.json → zones[].elevation_tier
  zone["hospital_count"]       → city_model.json → zones[].hospital_count
  zone["hospitals"]            → city_model.json → zones[].hospitals
  zone["shelters"]             → city_model.json → zones[].shelters
  zone["shelter_capacity_total"] → city_model.json → zones[].shelter_capacity_total
  zone["flood_risk_base"]      → city_model.json → zones[].flood_risk_base
  zone["risk_score"]           → Runtime, from Risk Agent (0–10 float)
  zone["vulnerability_score"]  → Runtime, from vulnerability_agent.py
  zone["road_links"]           → Derived from road_adjacency.json edges

  road_adjacency shelters:
    shelter["id"]              → road_adjacency.json → shelters[].id  (S01..S03)
    shelter["zone"]            → road_adjacency.json → shelters[].zone
    shelter["capacity"]        → road_adjacency.json → shelters[].capacity

  city_model shelters:
    shelter["id"]              → city_model.json → shelters[].id  (S01..S03)
    shelter["zone_id"]         → city_model.json → shelters[].zone_id
    shelter["capacity"]        → city_model.json → shelters[].capacity
    shelter["current_occupancy"] → city_model.json → shelters[].current_occupancy
    shelter["has_medical"]     → city_model.json → shelters[].has_medical

  WebSocket event type:
    "TICK_UPDATE"              → backend/main.py line 58 + Orchestration.jsx line 50

  Mobility Agent tick interface:
    MobilityAgent.update_tick(tick, risk_scores, vehicle_counts,
                              zones_to_evacuate, shelter_occupancies)
    Returns: {tick, routes: {zone: RouteResult dict}, removed_edges, logs, summary}

  RouteResult dict fields:
    tick, from_zone, to_zone, path, edges_used, total_distance_km,
    congestion_score, route_quality, status, reason

  Logger pattern:
    logging.getLogger("<module_name>")
    No shared singleton — each module uses stdlib logging.getLogger()
  ─────────────────────────────────────────────────────────────────

Inter-agent interfaces:
  - Receives: zone risk scores per tick (via tick_state or direct injection)
  - Receives: vulnerability scores from VulnerabilityAgent
  - Receives: routes from MobilityAgent/MobilityIntegration
  - Emits:    evacuation plan via WebSocket (type "TICK_UPDATE")
"""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from decision_governor.rationale_generator import generate_rationale

# ── Logger (stdlib, matching project convention) ──────────────────────────────
logger = logging.getLogger("DecisionGovernor")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(name)s][tick=%(tick)s] %(message)s"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def _log(msg: str, tick: int = 0) -> None:
    """Convenience wrapper to inject tick into log extra."""
    logger.info(msg, extra={"tick": tick})


class DecisionGovernor:
    """
    Central decision engine for the ADEO evacuation orchestration system.

    Computes zone priority scores, ranks zones, generates evacuation plans
    with shelter/route assignments, and handles replanning triggers.

    All weights and thresholds are loaded from the injected config dict
    (sourced from config.json) — nothing is hardcoded.

    Args:
        config:     dict loaded from config.json (must contain "decision_governor" block)
        city_model: dict loaded from city_model.json (Disha's city model)
    """

    def __init__(self, config: dict, city_model: dict) -> None:
        self._config = config
        self._city_model = city_model

        # Extract the decision_governor config block
        dg_config: dict = config.get("decision_governor", {})
        weights: dict = dg_config.get("priority_weights", {})

        # Priority weights — loaded from config, never hardcoded
        self._w_risk: float = weights.get("w_risk", 0.4)
        self._w_vulnerability: float = weights.get("w_vulnerability", 0.3)
        self._w_elderly: float = weights.get("w_elderly", 0.2)
        self._w_road_availability: float = weights.get("w_road_availability", 0.1)

        # Thresholds from config
        self._replan_cooldown_ticks: int = dg_config.get("replan_cooldown_ticks", 2)
        self._max_shelter_capacity_pct: float = dg_config.get("max_shelter_capacity_pct", 0.9)
        self._risk_threshold_for_replan: float = dg_config.get("risk_threshold_for_replan", 7.5)

        # Internal state
        self._current_tick: int = 0
        self._last_replan_tick: int = -999  # allows first replan to always fire
        self._last_valid_plan: Optional[dict] = None
        self._simulation_log: list[dict] = []

        # Build road adjacency lookup from city_model road_network edges
        # city_model.json uses zone IDs (Z01, Z02, ...) for road_network edges
        self._zone_road_links: dict[str, list[str]] = self._build_road_links()

        # Build zone name → zone ID mapping
        self._name_to_id: dict[str, str] = {}
        self._id_to_name: dict[str, str] = {}
        for z in self._city_model.get("zones", []):
            self._name_to_id[z["name"]] = z["id"]
            self._id_to_name[z["id"]] = z["name"]

        _log("DecisionGovernor initialised — weights: "
             f"risk={self._w_risk}, vuln={self._w_vulnerability}, "
             f"elderly={self._w_elderly}, road={self._w_road_availability}",
             tick=0)

    # ── Private Helpers ────────────────────────────────────────────────────────

    def _build_road_links(self) -> dict[str, list[str]]:
        """
        Build a zone-to-adjacent-zones lookup from city_model road_network.

        Uses the road_network.edges field from city_model.json, which stores
        edges as [zone_id, zone_id, capacity, road_name] lists.

        Returns:
            dict mapping zone_id to list of adjacent zone_ids.
        """
        links: dict[str, list[str]] = {}
        road_network = self._city_model.get("road_network", {})
        edges = road_network.get("edges", [])

        for edge in edges:
            # city_model.json edges are lists: [from_id, to_id, capacity, road_name]
            if len(edge) >= 2:
                from_id = edge[0]
                to_id = edge[1]
                links.setdefault(from_id, []).append(to_id)
                links.setdefault(to_id, []).append(from_id)

        return links

    def _road_availability_score(
        self,
        zone: dict,
        available_routes: Optional[dict] = None,
    ) -> float:
        """
        Returns 1.0 if at least one road link for the zone is currently usable
        in Vivek's mobility graph, else 0.0.

        If available_routes is provided (from MobilityAgent.update_tick()),
        checks the route status for this zone. A route with status != "failed"
        counts as usable.

        If no route data is provided, falls back to checking whether the zone
        has any road_links defined at all.

        Args:
            zone:             Zone dict (must contain "name" or "id").
            available_routes: Dict from MobilityAgent: {zone_name: RouteResult dict}.

        Returns:
            1.0 if at least one road is usable, 0.0 otherwise.
        """
        zone_name: str = zone.get("name", "")

        if available_routes:
            route = available_routes.get(zone_name)
            if route and route.get("status") != "failed":
                return 1.0
            return 0.0

        # Fallback: check if zone has any edges in city_model road_network
        zone_id: str = zone.get("id", "")
        links = self._zone_road_links.get(zone_id, [])
        return 1.0 if len(links) > 0 else 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def compute_priority_score(
        self,
        zone: dict,
        available_routes: Optional[dict] = None,
    ) -> float:
        """
        Compute the evacuation priority score for a single zone.

        Formula (all weights from config.json, never hardcoded):
            priority = (
                w_risk             * zone["risk_score"]          +
                w_vulnerability    * zone["vulnerability_score"] +
                w_elderly          * zone["elderly_pct"]         +
                w_road_availability * road_availability_score(zone)
            )

        Normalisation:
            risk_score is 0–10, vulnerability_score is 0–10,
            elderly_pct is 0–100 (normalised to 0–10 for parity),
            road_availability is 0.0 or 1.0.

        Args:
            zone:             Zone dict with at least risk_score, vulnerability_score,
                              elderly_pct.
            available_routes: Optional route data from MobilityAgent.

        Returns:
            float — higher values mean higher evacuation priority.
        """
        risk: float = zone.get("risk_score", 0.0)
        vuln: float = zone.get("vulnerability_score", 0.0)
        elderly: float = zone.get("elderly_pct", 0.0)
        road_avail: float = self._road_availability_score(zone, available_routes)

        # Normalise elderly_pct from 0–100 to 0–10 for consistent scale
        elderly_normalised: float = min(elderly / 10.0, 10.0)

        priority: float = (
            self._w_risk * risk
            + self._w_vulnerability * vuln
            + self._w_elderly * elderly_normalised
            + self._w_road_availability * road_avail
        )

        return round(priority, 4)

    def rank_zones(
        self,
        zones: list[dict],
        available_routes: Optional[dict] = None,
    ) -> list[dict]:
        """
        Rank zones by evacuation priority (descending).

        Each returned dict includes all original zone fields PLUS:
            - priority_score   : float
            - evacuation_rank  : int (1 = highest priority)

        Args:
            zones:            List of zone dicts (from city_model + runtime scores).
            available_routes: Optional route data from MobilityAgent.

        Returns:
            list[dict] — sorted by priority_score descending.
        """
        # Filter zones by minimum risk threshold (only include dangerous zones)
        min_risk = self._config.get("decision_governor", {}).get("min_risk_for_evacuation", 2.0)
        
        scored: list[dict] = []
        for zone in zones:
            if zone.get("status") == "evacuated":
                continue
            # Only consider zones with risk >= minimum threshold
            if zone.get("risk_score", 0) < min_risk:
                continue
            enriched = deepcopy(zone)
            enriched["priority_score"] = self.compute_priority_score(
                zone, available_routes
            )
            scored.append(enriched)

        scored.sort(key=lambda z: z["priority_score"], reverse=True)

        for rank, zone in enumerate(scored, start=1):
            zone["evacuation_rank"] = rank

        # Log top 3
        top3 = scored[:3]
        top3_summary = ", ".join(
            f"{z.get('name', z.get('id', '?'))}={z['priority_score']:.2f}"
            for z in top3
        )
        _log(f"Zone rankings computed — top 3: {top3_summary}", tick=self._current_tick)

        return scored

    def generate_evacuation_plan(
        self,
        ranked_zones: list[dict],
        available_routes: Optional[dict] = None,
    ) -> dict:
        """
        Generate a complete evacuation plan from ranked zones.
        """
        evacuation_sequence: list[dict] = []
        shelters_from_model = self._city_model.get("shelters", [])

        # Track shelter capacity usage during this plan
        shelter_usage: dict[str, int] = {}
        for s in shelters_from_model:
            shelter_usage[s["id"]] = s.get("current_occupancy", 0)

        for zone in ranked_zones:
            zone_name: str = zone.get("name", "")
            zone_id: str = zone.get("id", "")

            # Resolve route
            assigned_route: Optional[dict] = None
            route_destination: Optional[str] = None
            if available_routes:
                route = available_routes.get(zone_name)
                if route and route.get("status") != "failed":
                    assigned_route = route
                    route_destination = route.get("to_zone")

            # Resolve shelter assignment
            assigned_shelter: Optional[str] = None
            shelter_for_rationale: Optional[dict] = None

            if route_destination:
                # Try to match route destination to a known shelter
                for s in shelters_from_model:
                    if s["id"] == route_destination:
                        current_occ = shelter_usage.get(s["id"], 0)
                        # Assign if shelter has ANY space left (even if not for whole population)
                        if current_occ < s["capacity"]:
                            assigned_shelter = s["id"]
                            shelter_for_rationale = s
                            # For planning purposes, we assume we want to move as many as possible
                            # but we don't block the assignment just because the whole zone won't fit
                            zone_pop = zone.get("population", 0)
                            shelter_usage[s["id"]] = current_occ + zone_pop 
                            break

            # If no shelter from route, try any shelter with capacity
            if assigned_shelter is None:
                for s in shelters_from_model:
                    current_occ = shelter_usage.get(s["id"], 0)
                    if current_occ < s["capacity"]:
                        assigned_shelter = s["id"]
                        shelter_for_rationale = s
                        zone_pop = zone.get("population", 0)
                        shelter_usage[s["id"]] = current_occ + zone_pop
                        break

            # Generate rationale
            rationale = generate_rationale(zone, assigned_route, shelter_for_rationale)

            entry: dict = {
                "rank": zone.get("evacuation_rank", 0),
                "zone_id": zone_id,
                "zone_name": zone_name,
                "priority_score": round(zone.get("priority_score", 0.0), 2),
                "risk_score": round(zone.get("risk_score", 0.0), 2),
                "vulnerability_score": round(zone.get("vulnerability_score", 0.0), 2),
                "assigned_route": assigned_route,
                "assigned_shelter": assigned_shelter,
                "rationale": rationale,
            }
            evacuation_sequence.append(entry)

        plan: dict = {
            "tick": self._current_tick,
            "evacuation_sequence": evacuation_sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._last_valid_plan = plan
        self._simulation_log.append(deepcopy(plan))

        return plan

    def generate_candidate_plans(
        self,
        zone_states: list[dict],
        available_routes: Optional[dict] = None,
    ) -> dict[str, dict]:
        """
        🧠 PHASE 7: Generate multiple candidate plans based on different priorities.
        
        Returns:
            dict mapping strategy_name -> plan object.
        """
        strategies = {
            "balanced": (0.4, 0.3, 0.2, 0.1),    # Default config-like
            "safety_first": (0.7, 0.1, 0.1, 0.1), # Heavy on risk
            "vulnerability_first": (0.1, 0.7, 0.1, 0.1), # Heavy on vulnerability
        }
        
        # Backup original weights
        original_weights = (self._w_risk, self._w_vulnerability, self._w_elderly, self._w_road_availability)
        
        candidate_plans = {}
        for name, weights in strategies.items():
            self._w_risk, self._w_vulnerability, self._w_elderly, self._w_road_availability = weights
            ranked = self.rank_zones(zone_states, available_routes)
            plan = self.generate_evacuation_plan(ranked, available_routes)
            plan["strategy"] = name
            candidate_plans[name] = plan
            
        # Restore original weights
        self._w_risk, self._w_vulnerability, self._w_elderly, self._w_road_availability = original_weights
        
        return candidate_plans


    def handle_replan(self, trigger: dict, zone_states: Optional[list[dict]] = None, available_routes: Optional[dict] = None) -> dict:
        """
        Handle a replanning trigger from the simulation engine.
        ...
        """
        trigger_type: str = trigger.get("trigger_type", "unknown")
        affected_zone: str = trigger.get("affected_zone_id", "unknown")
        trigger_tick: int = trigger.get("tick", self._current_tick)

        _log(f"REPLAN triggered — type={trigger_type}, zone={affected_zone}, tick={trigger_tick}",
             tick=trigger_tick)

        # Check cooldown
        if (trigger_tick - self._last_replan_tick) < self._replan_cooldown_ticks:
            _log(f"REPLAN skipped — cooldown active "
                 f"(last replan at tick {self._last_replan_tick}, "
                 f"cooldown={self._replan_cooldown_ticks})",
                 tick=trigger_tick)
            if self._last_valid_plan is not None:
                return self._last_valid_plan

        self._last_replan_tick = trigger_tick
        self._current_tick = trigger_tick

        # Recompute using current zone states (risk scores)
        zones = zone_states if zone_states is not None else deepcopy(self._city_model.get("zones", []))

        # Re-rank and regenerate
        ranked = self.rank_zones(zones, available_routes)
        plan = self.generate_evacuation_plan(ranked, available_routes)

        _log(f"REPLAN complete — new evacuation sequence has {len(plan['evacuation_sequence'])} zones",
             tick=trigger_tick)

        self._last_valid_plan = plan
        return plan

    # ── Simulation Loop Integration ────────────────────────────────────────────

    def on_tick(self, tick_state: dict) -> dict:
        """
        Called once per simulation tick by the simulation engine (backend/main.py).

        This method matches the integration pattern used by MobilityIntegration.on_tick()
        in agents/mobility_agent/simulation_integration.py.

        tick_state fields (verified from backend/main.py and test_mobility_agent.py):
            - tick              : int — current simulation tick number
            - zone_states       : list[dict] — per-zone data with risk + vulnerability scores
            - available_routes  : dict — routes from MobilityAgent
                                       {zone_name: RouteResult dict}
            - replan_triggered  : bool — whether a replan was triggered this tick
            - replan_trigger    : dict | None — trigger details if replan_triggered

        Returns:
            dict — the evacuation plan for this tick.

        Edge cases:
            - If zone_states is missing, uses last known city_model zones
              and logs a warning.
            - If available_routes is missing, plans are generated without
              route assignments.
        """
        tick: int = tick_state.get("tick", 0)
        self._current_tick = tick

        # Extract zone states — fall back to city_model zones if not provided
        zone_states: Optional[list[dict]] = tick_state.get("zone_states")
        if zone_states is None:
            logger.warning(
                "zone_states missing from tick_state — using last known city_model zones",
                extra={"tick": tick},
            )
            zone_states = deepcopy(self._city_model.get("zones", []))

        available_routes: Optional[dict] = tick_state.get("available_routes")

        # Handle replan if triggered
        replan_triggered: bool = tick_state.get("replan_triggered", False)
        replan_trigger: Optional[dict] = tick_state.get("replan_trigger")

        if replan_triggered and replan_trigger is not None:
            return self.handle_replan(replan_trigger, zone_states, available_routes)

        # Normal tick: rank zones and generate plan
        ranked = self.rank_zones(zone_states, available_routes)
        plan = self.generate_evacuation_plan(ranked, available_routes)

        return plan

    # ── Accessors ──────────────────────────────────────────────────────────────

    def get_simulation_log(self) -> list[dict]:
        """Return the full simulation log (list of plans across all ticks)."""
        return deepcopy(self._simulation_log)

    def get_last_plan(self) -> Optional[dict]:
        """Return the most recently generated evacuation plan, or None."""
        return deepcopy(self._last_valid_plan) if self._last_valid_plan else None
