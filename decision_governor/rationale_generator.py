"""
decision_governor/rationale_generator.py
==========================================
Generates human-readable rationale strings explaining each zone's
evacuation decision.

Hybrid mode:
  - Template-based rationale (always available, instant)
  - LLM-generated rationale (when Ollama is available, richer language)

All values are dynamically interpolated from the zone dict — no
hardcoded zone names, scores, route names, or shelter identifiers.

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

import json
import logging
from typing import Optional

logger = logging.getLogger("RationaleGenerator")

# Module-level reference to the shared Ollama client
# Set by the backend at startup via set_ollama_client()
_ollama_client = None


def set_ollama_client(client) -> None:
    """Inject the shared OllamaClient instance."""
    global _ollama_client
    _ollama_client = client


def generate_rationale(
    zone: dict,
    route: Optional[dict],
    shelter: Optional[dict],
) -> str:
    """
    Produce a human-readable rationale string for a single zone decision.
    This is the synchronous template-based version (always available).

    Rules:
        - Never hardcode zone names, scores, or route names
        - All values dynamically interpolated from zone dict
        - Maximum 3 sentences
        - Readable by non-technical stakeholders

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
        f"Zone {zone_name} was ranked {rank_label} for evacuation "
        f"due to its {risk_label} (risk score {risk_score:.1f}/10) "
        f"and high vulnerability factors, including an elderly population of {elderly_pct:.1f}%."
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


async def generate_llm_rationale(
    zone: dict,
    route: Optional[dict],
    shelter: Optional[dict],
) -> str:
    """
    Generate LLM-powered rationale for a zone's evacuation decision.
    Falls back to template-based rationale if Ollama is unavailable.

    Args:
        zone:     Zone dict with risk_score, vulnerability_score, elderly_pct, etc.
        route:    RouteResult dict from MobilityAgent, or None.
        shelter:  Shelter dict from city_model, or None.

    Returns:
        str — natural language rationale (2-3 sentences).
    """
    # Always have fallback ready
    template_rationale = generate_rationale(zone, route, shelter)

    if _ollama_client is None or not await _ollama_client.is_available():
        return template_rationale

    zone_name = zone.get("name", "Unknown")
    risk_score = zone.get("risk_score", 0.0)
    vuln_score = zone.get("vulnerability_score", 0.0)
    elderly_pct = zone.get("elderly_pct", 0.0)
    rank = zone.get("evacuation_rank", 0)
    priority = zone.get("priority_score", 0.0)
    elevation = zone.get("elevation_tier", "mid")

    # Build context
    context = {
        "zone_name": zone_name,
        "evacuation_rank": rank,
        "risk_score": risk_score,
        "vulnerability_score": vuln_score,
        "elderly_pct": elderly_pct,
        "elevation_tier": elevation,
        "priority_score": priority,
    }

    if route and route.get("status") != "failed":
        context["route_status"] = "available"
        context["route_distance_km"] = route.get("total_distance_km", 0)
        context["route_quality"] = route.get("route_quality", 0)
        context["route_destination"] = route.get("to_zone", "unknown")
    elif route:
        context["route_status"] = "failed"
        context["route_failure_reason"] = route.get("reason", "unknown")
    else:
        context["route_status"] = "no data"

    if shelter:
        context["shelter_name"] = shelter.get("name", "Unknown")
        context["shelter_capacity"] = shelter.get("capacity", 0)
        context["shelter_occupancy"] = shelter.get("current_occupancy", 0)
    else:
        context["shelter"] = "none available"

    system_prompt = (
        "You are a disaster evacuation analyst writing brief decision rationales "
        "for emergency coordinators. Be concise, specific, and actionable. "
        "Write exactly 2-3 sentences. Use the data provided, do not invent data."
    )

    prompt = (
        f"Write a concise rationale for this evacuation decision:\n\n"
        f"{json.dumps(context, indent=1)}\n\n"
        f"Explain why this zone is ranked #{rank} for evacuation "
        f"and what the current route/shelter situation is. "
        f"2-3 sentences only, plain English."
    )

    try:
        result = await _ollama_client.generate(
            prompt=prompt,
            system=system_prompt,
            temperature=0.4,
            max_tokens=200,
        )
        if result and len(result) > 20:
            return result.strip()
    except Exception as e:
        logger.warning(f"LLM rationale generation failed: {e}")

    return template_rationale


async def generate_batch_rationales(
    ranked_zones: list[dict],
    available_routes: Optional[dict],
    shelters: list[dict],
) -> dict[str, str]:
    """
    Generate LLM rationales for all zones in a single batch call.
    More efficient than calling generate_llm_rationale() per zone.

    Returns: dict mapping zone_name -> rationale string.
    """
    if _ollama_client is None or not await _ollama_client.is_available():
        return {}

    # Build compact batch data
    batch_data = []
    for zone in ranked_zones[:6]:  # Limit to top 6 for prompt length
        entry = {
            "zone": zone.get("name", "?"),
            "rank": zone.get("evacuation_rank", 0),
            "risk": zone.get("risk_score", 0.0),
            "vuln": zone.get("vulnerability_score", 0.0),
            "elderly_pct": zone.get("elderly_pct", 0.0),
        }

        zone_name = zone.get("name", "")
        if available_routes and zone_name in available_routes:
            route = available_routes[zone_name]
            if isinstance(route, dict):
                entry["route"] = route.get("status", "unknown")
                entry["distance_km"] = route.get("total_distance_km", 0)
        batch_data.append(entry)

    system_prompt = (
        "You are a disaster evacuation analyst. Write brief decision rationales "
        "for emergency coordinators. Be concise and specific."
    )

    prompt = (
        "For each zone below, write a 1-2 sentence evacuation rationale:\n\n"
        f"{json.dumps(batch_data, indent=1)}\n\n"
        "Respond ONLY with a JSON object mapping zone names to rationale strings:\n"
        '{"Zone_Name": "rationale text", ...}\n'
        "No markdown, no extra text."
    )

    try:
        result = await _ollama_client.generate_json(
            prompt=prompt,
            system=system_prompt,
            temperature=0.4,
            max_tokens=600,
        )
        if result and isinstance(result, dict):
            return {k: str(v) for k, v in result.items() if isinstance(v, str)}
    except Exception as e:
        logger.warning(f"Batch LLM rationale failed: {e}")

    return {}


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
