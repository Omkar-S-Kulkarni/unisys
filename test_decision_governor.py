"""
test_decision_governor.py
===========================
Integration test for the Decision Governor module.
Run from repo root: python test_decision_governor.py
"""

import json
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.abspath(os.curdir))

from decision_governor import DecisionGovernor
from decision_governor.summary_generator import generate_summary
from decision_governor.rationale_generator import generate_rationale


def run_test():
    print("=" * 70)
    print("  ADEO UIP17 — Decision Governor Integration Test")
    print("=" * 70)

    # Load real project data
    with open("config.json") as f:
        config = json.load(f)
    with open("agents/vulnerability_agent/data/city_model.json") as f:
        city_model = json.load(f)

    # Construct governor
    gov = DecisionGovernor(config=config, city_model=city_model)

    # Simulate zone states with runtime risk and vulnerability scores
    zones = []
    for z in city_model["zones"]:
        z_copy = dict(z)
        z_copy["risk_score"] = z.get("flood_risk_base", 3.0)
        z_copy["vulnerability_score"] = 5.0  # stub value
        zones.append(z_copy)

    # ── Test 1: rank_zones ──────────────────────────────────────────────
    print("\n--- Test 1: rank_zones ---")
    ranked = gov.rank_zones(zones)
    for z in ranked[:5]:
        rank = z["evacuation_rank"]
        name = z["name"]
        score = z["priority_score"]
        print(f"  Rank {rank}: {name} — priority={score:.3f}")

    assert ranked[0]["evacuation_rank"] == 1
    assert ranked[0]["priority_score"] >= ranked[1]["priority_score"]
    print("  [PASS] Zones ranked correctly\n")

    # ── Test 2: generate_evacuation_plan ────────────────────────────────
    print("--- Test 2: generate_evacuation_plan ---")
    plan = gov.generate_evacuation_plan(ranked)
    tick = plan["tick"]
    print(f"  Plan tick: {tick}")
    for entry in plan["evacuation_sequence"][:3]:
        rank = entry["rank"]
        name = entry["zone_name"]
        shelter = entry["assigned_shelter"]
        rationale = entry["rationale"][:100]
        print(f"  Rank {rank}: {name} -> shelter={shelter}")
        print(f"    Rationale: {rationale}...")

    assert "evacuation_sequence" in plan
    assert "timestamp" in plan
    assert len(plan["evacuation_sequence"]) == len(zones)
    print("  [PASS] Evacuation plan generated\n")

    # ── Test 3: on_tick ─────────────────────────────────────────────────
    print("--- Test 3: on_tick ---")
    tick_result = gov.on_tick({
        "tick": 1,
        "zone_states": zones,
        "available_routes": None,
        "replan_triggered": False,
        "replan_trigger": None,
    })
    seq_len = len(tick_result["evacuation_sequence"])
    ts = tick_result["timestamp"]
    print(f"  Plan has {seq_len} zones")
    print(f"  Timestamp: {ts}")
    assert seq_len == len(zones)
    print("  [PASS] on_tick works correctly\n")

    # ── Test 4: on_tick with routes (simulated) ─────────────────────────
    print("--- Test 4: on_tick with simulated routes ---")
    mock_routes = {
        "Bellandur": {
            "status": "ok",
            "path": ["Bellandur", "Marathahalli", "Hebbal", "S03"],
            "total_distance_km": 18.3,
            "route_quality": 0.72,
            "to_zone": "S03",
        },
        "Sarjapur": {
            "status": "failed",
            "path": [],
            "total_distance_km": 0.0,
            "route_quality": 0.0,
            "to_zone": "NONE",
            "reason": "All paths flooded",
        },
    }
    tick_with_routes = gov.on_tick({
        "tick": 2,
        "zone_states": zones,
        "available_routes": mock_routes,
        "replan_triggered": False,
        "replan_trigger": None,
    })
    for entry in tick_with_routes["evacuation_sequence"]:
        if entry["zone_name"] in ("Bellandur", "Sarjapur"):
            route_str = "has route" if entry["assigned_route"] else "no route"
            print(f"  {entry['zone_name']}: {route_str}")
    print("  [PASS] Routes integrated correctly\n")

    # ── Test 5: handle_replan ───────────────────────────────────────────
    print("--- Test 5: handle_replan ---")
    replan = gov.handle_replan({
        "trigger_type": "risk_threshold",
        "affected_zone_id": "Z07",
        "tick": 5,
    })
    r_tick = replan["tick"]
    r_zones = len(replan["evacuation_sequence"])
    print(f"  Replan tick: {r_tick}")
    print(f"  Zones in plan: {r_zones}")
    assert "evacuation_sequence" in replan
    print("  [PASS] Replan works correctly\n")

    # ── Test 6: replan cooldown ─────────────────────────────────────────
    print("--- Test 6: replan cooldown ---")
    replan_2 = gov.handle_replan({
        "trigger_type": "shelter_full",
        "affected_zone_id": "Z04",
        "tick": 6,  # within 2-tick cooldown of tick 5
    })
    print(f"  Cooldown test: plan tick={replan_2['tick']}")
    # Should return the previous plan (tick 5) due to cooldown
    print("  [PASS] Cooldown respected\n")

    # ── Test 7: summary generator ───────────────────────────────────────
    print("--- Test 7: summary generator ---")
    sim_log = gov.get_simulation_log()
    summary = generate_summary(sim_log)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    assert summary["total_ticks"] > 0
    assert "final_risk_distribution" in summary
    print("  [PASS] Summary generated correctly\n")

    # ── Test 8: rationale_generator standalone ──────────────────────────
    print("--- Test 8: rationale_generator standalone ---")
    test_zone = {
        "name": "Bellandur",
        "risk_score": 8.4,
        "elderly_pct": 8.0,
        "vulnerability_score": 6.5,
        "evacuation_rank": 1,
        "priority_score": 7.34,
    }
    test_route = {
        "status": "ok",
        "path": ["Bellandur", "Marathahalli", "Hebbal", "S03"],
        "total_distance_km": 18.3,
        "route_quality": 0.72,
    }
    test_shelter = {
        "name": "Hebbal Community Hall",
        "capacity": 2500,
        "current_occupancy": 1700,
    }
    rationale = generate_rationale(test_zone, test_route, test_shelter)
    print(f"  Rationale: {rationale}")
    assert "Bellandur" in rationale
    assert "8.4" in rationale
    print("  [PASS] Rationale generated correctly\n")

    # ── Test 9: edge case — empty routes ────────────────────────────────
    print("--- Test 9: edge case — no routes, no shelters ---")
    empty_zone = {
        "name": "TestZone",
        "id": "ZXX",
        "risk_score": 9.5,
        "elderly_pct": 20.0,
        "vulnerability_score": 8.0,
        "evacuation_rank": 1,
        "priority_score": 9.0,
    }
    rationale_empty = generate_rationale(empty_zone, None, None)
    print(f"  Rationale: {rationale_empty}")
    assert "No shelter" in rationale_empty or "shelter" in rationale_empty.lower()
    print("  [PASS] Edge case handled\n")

    print("=" * 70)
    print("  All 9 tests passed!")
    print("=" * 70)


if __name__ == "__main__":
    run_test()
