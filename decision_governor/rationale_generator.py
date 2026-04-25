"""
decision_governor/rationale_generator.py
==========================================
Generates human-readable rationale strings explaining each zone's
evacuation decision.

All values are dynamically interpolated from the zone dict — no
hardcoded zone names, scores, route names, or shelter identifiers.

Output is designed for non-technical stakeholders: maximum 3 sentences,
plain English, with key metrics cited.

Verified field names:
    zone["name"]                → city_model.json → zones[].name
    zone["risk_score"]          → Runtime from Risk Agent (0–10)
    zone["vulnerability_score"] → Runtime from vulnerability_agent.py
    zone["elderly_pct"]         → city_model.json → zones[].elderly_pct
    zone["priority_score"]      → Computed by DecisionGovernor.rank_zones()
    zone["evacuation_rank"]     → Computed by DecisionGovernor.rank_zones()
    zone["elevation_tier"]      → city_model.json → zones[].elevation_tier
    route["path"]               → MobilityAgent RouteResult.path
    route["total_distance_km"]  → MobilityAgent RouteResult.total_distance_km
    route["route_quality"]      → MobilityAgent RouteResult.route_quality
    route["status"]             → MobilityAgent RouteResult.status
    shelter["name"]             → city_model.json → shelters[].name
    shelter["capacity"]         → city_model.json → shelters[].capacity
    shelter["current_occupancy"] → city_model.json → shelters[].current_occupancy
"""

from __future__ import annotations

from typing import Optional


def generate_rationale(
    zone: dict,
    route: Optional[dict],
    shelter: Optional[dict],
) -> str:
    """
    Produce a human-readable rationale string for a single zone decision.

    Rules:
        - Never hardcode zone names, scores, or route names
        - All values dynamically interpolated from zone dict
        - Maximum 3 sentences
        - Readable by non-technical stakeholders

    Example output:
        "Zone Bellandur evacuated first: risk score 8.4/10 (severe flooding),
         elderly population 22.3%. Route via Sarjapur Road available,
         assigned to Shelter S2 (capacity 68% used)."

    Args:
        zone:     Zone dict with at minimum name, risk_score, elderly_pct,
                  vulnerability_score, priority_score, evacuation_rank.
        route:    RouteResult dict from MobilityAgent, or None if no route.
        shelter:  Shelter dict from city_model, or None if no shelter available.

    Returns:
        str — human-readable rationale (1–3 sentences).
    """
    zone_name: str = zone.get("name", "Unknown")
    risk_score: float = zone.get("risk_score", 0.0)
    elderly_pct: float = zone.get("elderly_pct", 0.0)
    rank: int = zone.get("evacuation_rank", 0)

    # Sentence 1: zone priority summary
    risk_label = _risk_label(risk_score)
    rank_label = _ordinal(rank)
    sentence_1 = (
        f"Zone {zone_name} ranked {rank_label} for evacuation: "
        f"risk score {risk_score:.1f}/10 ({risk_label}), "
        f"elderly population {elderly_pct:.1f}%."
    )

    # Sentence 2: route status
    if route is not None and route.get("status") != "failed":
        path = route.get("path", [])
        path_summary = " -> ".join(path) if path else "direct"
        distance = route.get("total_distance_km", 0.0)
        quality = route.get("route_quality", 0.0)
        sentence_2 = (
            f"Route available ({path_summary}, "
            f"{distance:.1f} km, quality {quality:.0%})."
        )
    elif route is not None and route.get("status") == "failed":
        reason = route.get("reason", "all paths blocked")
        sentence_2 = f"No viable route available: {reason}."
    else:
        sentence_2 = "Route data unavailable for this zone."

    # Sentence 3: shelter assignment
    if shelter is not None:
        shelter_name: str = shelter.get("name", "Unknown Shelter")
        capacity: int = shelter.get("capacity", 0)
        occupancy: int = shelter.get("current_occupancy", 0)
        if capacity > 0:
            usage_pct = (occupancy / capacity) * 100
            sentence_3 = (
                f"Assigned to {shelter_name} ({usage_pct:.0f}% capacity used)."
            )
        else:
            sentence_3 = f"Assigned to {shelter_name} (capacity data unavailable)."
    else:
        sentence_3 = "No shelter available — all shelters at capacity or inaccessible."

    return f"{sentence_1} {sentence_2} {sentence_3}"


def _risk_label(score: float) -> str:
    """Map a 0–10 risk score to a human-readable severity label."""
    if score >= 9.0:
        return "critical flooding"
    elif score >= 7.0:
        return "severe flooding"
    elif score >= 4.0:
        return "moderate risk"
    elif score >= 2.0:
        return "low risk"
    return "minimal risk"


def _ordinal(n: int) -> str:
    """Convert integer to ordinal string (1st, 2nd, 3rd, etc.)."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
