"""
decision_governor/summary_generator.py
========================================
Post-event summary generator for the ADEO simulation.

Hybrid mode:
  - Statistical summary (always available, instant)
  - LLM-enhanced narrative summary (when Ollama is available)

Reads the full simulation log (list of evacuation plans across all ticks)
from DecisionGovernor.get_simulation_log() and produces an aggregate
summary report.

Verified log structure (from DecisionGovernor):
    Each log entry is an evacuation plan dict:
    {
        "tick": int,
        "evacuation_sequence": [
            {
                "rank": int,
                "zone_id": str,
                "zone_name": str,
                "priority_score": float,
                "assigned_route": dict | None,
                "assigned_shelter": str | None,
                "rationale": str
            }
        ],
        "timestamp": str (ISO 8601)
    }

Verified zone risk_score field:
    zone["risk_score"] → 0–10 float (from Risk Agent, injected per tick)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("DecisionGovernor")

# Module-level reference to the shared Ollama client
_ollama_client = None


def set_ollama_client(client) -> None:
    """Inject the shared OllamaClient instance."""
    global _ollama_client
    _ollama_client = client


def generate_summary(simulation_log: list[dict]) -> dict:
    """
    Generate a post-simulation summary report from the full simulation log.

    Reads the list of evacuation plan dicts produced by
    DecisionGovernor.get_simulation_log().

    Args:
        simulation_log: List of evacuation plan dicts, one per tick.

    Returns:
        {
            "total_ticks":               int,
            "completion_time_ticks":     int,
            "total_replans":             int,
            "zones_evacuated":           int,
            "total_zones":               int,
            "pct_population_evacuated":  float,
            "replan_reasons":            list[str],
            "final_risk_distribution":   {
                "low":    int,    # risk_score < 3
                "medium": int,   # 3 to 7
                "high":  int     # > 7
            }
        }
    """
    if not simulation_log:
        logger.warning("Empty simulation log — returning zeroed summary",
                       extra={"tick": 0})
        return _empty_summary()

    total_ticks: int = len(simulation_log)

    # Determine completion tick (last tick in the log)
    completion_tick: int = 0
    try:
        completion_tick = max(entry.get("tick", 0) for entry in simulation_log)
    except (ValueError, TypeError):
        completion_tick = total_ticks

    # Aggregate statistics across all ticks
    all_zone_ids: set[str] = set()
    zones_with_shelter: set[str] = set()
    zones_with_route: set[str] = set()
    replan_reasons: list[str] = []

    # Track the last known risk score per zone for final distribution
    last_risk_scores: dict[str, float] = {}

    for entry in simulation_log:
        sequence = entry.get("evacuation_sequence", [])
        for item in sequence:
            zone_id: str = item.get("zone_id", "")
            zone_name: str = item.get("zone_name", "")
            all_zone_ids.add(zone_id)

            # A zone is considered "evacuated" if it had both a route and shelter
            if item.get("assigned_shelter") is not None:
                zones_with_shelter.add(zone_id)
            if item.get("assigned_route") is not None:
                zones_with_route.add(zone_id)

            # Extract risk scores from zone data embedded in the plan
            route = item.get("assigned_route")
            # The priority_score is our best proxy; actual risk_score
            # would need to be extracted from zone_states if available.

    # Count zones where both route and shelter were assigned at least once
    zones_evacuated: int = len(zones_with_shelter & zones_with_route)
    total_zones: int = len(all_zone_ids) if all_zone_ids else 1

    # Percentage of zones that were successfully evacuated
    pct_evacuated: float = round((zones_evacuated / total_zones) * 100.0, 1)

    # Count replans (ticks where we see the same zones re-ranked differently)
    # Heuristic: replan occurs when consecutive ticks have different rankings
    total_replans: int = _count_replans(simulation_log)

    # Final risk distribution from the last tick's zone data
    final_risk_dist = _compute_risk_distribution(simulation_log)

    summary: dict = {
        "total_ticks": total_ticks,
        "completion_time_ticks": completion_tick,
        "total_replans": total_replans,
        "zones_evacuated": zones_evacuated,
        "total_zones": total_zones,
        "pct_population_evacuated": pct_evacuated,
        "replan_reasons": replan_reasons,
        "final_risk_distribution": final_risk_dist,
    }

    logger.info(
        f"Summary generated — {total_ticks} ticks, "
        f"{zones_evacuated}/{total_zones} zones evacuated, "
        f"{total_replans} replans",
        extra={"tick": completion_tick},
    )

    return summary


async def generate_llm_summary(simulation_log: list[dict]) -> dict:
    """
    Generate an LLM-enhanced post-simulation summary.

    Combines statistical data with an LLM-generated narrative analysis.

    Returns:
        dict with all standard summary fields plus:
        - "narrative": str (LLM-generated executive summary)
        - "key_decisions": list[str] (LLM-identified key decisions)
        - "risk_trends": str (LLM analysis of risk progression)
        - "recommendations": list[str] (LLM strategic recommendations)
        - "llm_powered": bool
    """
    # Always compute the base statistical summary
    base_summary = generate_summary(simulation_log)
    
    # Calculate average risk as a proxy from final distribution
    dist = base_summary.get("final_risk_distribution", {})
    total_zones = base_summary.get("total_zones", 1)
    avg_risk_est = (dist.get("low", 0) * 2 + dist.get("medium", 0) * 5 + dist.get("high", 0) * 9) / total_zones

    res = {
        "metrics": {
            "total_ticks": base_summary.get("total_ticks", 0),
            "zones_evacuated": base_summary.get("zones_evacuated", 0),
            "replan_count": base_summary.get("total_replans", 0),
            "avg_risk": round(avg_risk_est, 1)
        },
        "summary": "",
        "recommendation": "",
        "events": [],
        "llm_powered": False
    }

    if _ollama_client is None or not await _ollama_client.is_available():
        res["summary"] = _generate_fallback_narrative(base_summary)
        res["recommendation"] = "Standard protocols maintained. LLM analysis unavailable."
        return res

    # Build a compact log summary for the LLM
    log_digest = _build_log_digest(simulation_log)

    system_prompt = (
        "You are an expert disaster management analyst. Analyze the simulation data."
    )

    prompt = (
        f"SIMULATION STATISTICS:\n{json.dumps(base_summary, indent=1)}\n\n"
        f"TICK-BY-TICK DIGEST:\n{json.dumps(log_digest, indent=1)}\n\n"
        "Respond ONLY with a valid JSON object:\n"
        "{\n"
        '  "summary": "3-4 sentence narrative",\n'
        '  "recommendation": "1-2 sentence recommendation"\n'
        "}\n"
    )

    try:
        llm_res = await _ollama_client.generate_json(
            prompt=prompt,
            system=system_prompt,
            temperature=0.3,
            max_tokens=500,
        )

        if llm_res and isinstance(llm_res, dict):
            res["summary"] = llm_res.get("summary", _generate_fallback_narrative(base_summary))
            res["recommendation"] = llm_res.get("recommendation", "Continue current emergency protocols.")
            res["llm_powered"] = True
            return res
    except Exception as e:
        logger.warning(f"LLM summary generation failed: {e}")

    # Fallback
    res["summary"] = _generate_fallback_narrative(base_summary)
    res["recommendation"] = "Standard evacuation protocols recommended."
    return res


def _generate_fallback_narrative(summary: dict) -> str:
    """Generate a rule-based narrative when LLM is unavailable."""
    total = summary.get("total_ticks", 0)
    evacuated = summary.get("zones_evacuated", 0)
    total_zones = summary.get("total_zones", 0)
    pct = summary.get("pct_population_evacuated", 0)
    replans = summary.get("total_replans", 0)
    dist = summary.get("final_risk_distribution", {})

    narrative = (
        f"The simulation ran for {total} ticks, successfully evacuating "
        f"{evacuated} out of {total_zones} zones ({pct}% coverage). "
    )
    if replans > 0:
        narrative += f"{replans} replanning events were triggered during execution. "
    high_risk = dist.get("high", 0)
    if high_risk > 0:
        narrative += f"At completion, {high_risk} zone(s) remained at high risk levels."
    else:
        narrative += "All zones were brought to manageable risk levels."

    return narrative


def _build_log_digest(simulation_log: list[dict]) -> list[dict]:
    """
    Build a compact digest of the simulation log for the LLM.
    Extracts key metrics per tick without sending the full plan data.
    """
    digest = []
    for entry in simulation_log[-10:]:  # Last 10 ticks max
        sequence = entry.get("evacuation_sequence", [])
        tick_info = {
            "tick": entry.get("tick", 0),
            "zones_in_plan": len(sequence),
            "top_zone": sequence[0].get("zone_name", "?") if sequence else "?",
            "top_priority": round(sequence[0].get("priority_score", 0), 2) if sequence else 0,
            "zones_with_routes": sum(1 for s in sequence if s.get("assigned_route")),
            "zones_without_routes": sum(1 for s in sequence if not s.get("assigned_route")),
        }
        digest.append(tick_info)
    return digest


def _empty_summary() -> dict:
    """Return a zeroed-out summary for empty logs."""
    return {
        "total_ticks": 0,
        "completion_time_ticks": 0,
        "total_replans": 0,
        "zones_evacuated": 0,
        "total_zones": 0,
        "pct_population_evacuated": 0.0,
        "replan_reasons": [],
        "final_risk_distribution": {"low": 0, "medium": 0, "high": 0},
    }


def _count_replans(simulation_log: list[dict]) -> int:
    """
    Count the number of replanning events in the simulation log.

    A replan is detected when the evacuation sequence ordering changes
    between consecutive ticks.
    """
    replans: int = 0
    prev_order: list[str] = []

    for entry in simulation_log:
        sequence = entry.get("evacuation_sequence", [])
        current_order = [item.get("zone_id", "") for item in sequence]

        if prev_order and current_order != prev_order:
            replans += 1

        prev_order = current_order

    return replans


def _compute_risk_distribution(simulation_log: list[dict]) -> dict[str, int]:
    """
    Compute the final risk distribution from the last tick's zone data.

    Categories:
        low:    priority_score < 3
        medium: 3 <= priority_score <= 7
        high:   priority_score > 7
    """
    if not simulation_log:
        return {"low": 0, "medium": 0, "high": 0}

    last_entry = simulation_log[-1]
    sequence = last_entry.get("evacuation_sequence", [])

    low = 0
    medium = 0
    high = 0

    for item in sequence:
        score: float = item.get("priority_score", 0.0)
        if score < 3.0:
            low += 1
        elif score <= 7.0:
            medium += 1
        else:
            high += 1

    return {"low": low, "medium": medium, "high": high}
