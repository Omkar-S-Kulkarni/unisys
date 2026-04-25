"""
test_mobility_agent.py
========================
End-to-end test: simulates 5 ticks of a flood scenario.
Run from the repo root: python test_mobility_agent.py
"""

import json
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.abspath(os.curdir))

from agents.mobility_agent.simulation_integration import MobilityIntegration

# ── Simulate 5 ticks with escalating flood severity ───────────────────────────

TICKS = [
    # tick 1: calm
    {
        "tick": 1,
        "zone_risk_scores": {
            "Bellandur": 2.0, "Sarjapur": 1.5, "Whitefield": 1.0,
            "HSR Layout": 1.2, "Koramangala": 1.0, "BTM Layout": 1.3,
            "Jayanagar": 0.8, "Rajajinagar": 0.5, "Hebbal": 0.6,
            "Yelahanka": 0.4, "Electronic City": 1.1, "Marathahalli": 1.0,
        },
        "vehicle_counts": {z: 200 for z in [
            "Bellandur","Sarjapur","Whitefield","HSR Layout","Koramangala",
            "BTM Layout","Jayanagar","Rajajinagar","Hebbal","Yelahanka",
            "Electronic City","Marathahalli"
        ]},
        "shelter_occupancies": {"S1": 100, "S2": 50, "S3": 0, "S4": 0, "S5": 0},
        "zones_to_evacuate": ["Bellandur", "Sarjapur", "HSR Layout"],
    },
    # tick 2: moderate flood
    {
        "tick": 2,
        "zone_risk_scores": {
            "Bellandur": 5.5, "Sarjapur": 6.0, "Whitefield": 3.0,
            "HSR Layout": 4.5, "Koramangala": 4.0, "BTM Layout": 5.0,
            "Jayanagar": 2.0, "Rajajinagar": 1.5, "Hebbal": 1.8,
            "Yelahanka": 1.0, "Electronic City": 4.2, "Marathahalli": 3.5,
        },
        "vehicle_counts": {
            "Bellandur": 800, "Sarjapur": 600, "HSR Layout": 500,
            "Koramangala": 900, "BTM Layout": 700,
        },
        "shelter_occupancies": {"S1": 500, "S2": 200, "S3": 100, "S4": 150, "S5": 80},
        "zones_to_evacuate": ["Bellandur", "Sarjapur", "HSR Layout", "BTM Layout", "Koramangala"],
    },
    # tick 3: severe flood — some roads should be removed
    {
        "tick": 3,
        "zone_risk_scores": {
            "Bellandur": 7.5, "Sarjapur": 8.0, "Whitefield": 5.0,
            "HSR Layout": 7.0, "Koramangala": 6.5, "BTM Layout": 7.2,
            "Jayanagar": 4.0, "Rajajinagar": 2.0, "Hebbal": 2.5,
            "Yelahanka": 1.5, "Electronic City": 6.5, "Marathahalli": 5.5,
        },
        "vehicle_counts": {
            "Bellandur": 1500, "Sarjapur": 1200, "HSR Layout": 1000,
            "Koramangala": 1800, "BTM Layout": 1600, "Electronic City": 1400,
        },
        "shelter_occupancies": {"S1": 2000, "S2": 1000, "S3": 500, "S4": 1500, "S5": 800},
        "zones_to_evacuate": [
            "Bellandur", "Sarjapur", "HSR Layout", "BTM Layout",
            "Koramangala", "Whitefield", "Electronic City"
        ],
    },
    # tick 4: extreme — test route failures
    {
        "tick": 4,
        "zone_risk_scores": {
            "Bellandur": 9.0, "Sarjapur": 9.5, "Whitefield": 7.0,
            "HSR Layout": 8.5, "Koramangala": 8.0, "BTM Layout": 9.0,
            "Jayanagar": 6.0, "Rajajinagar": 3.5, "Hebbal": 4.0,
            "Yelahanka": 2.0, "Electronic City": 8.0, "Marathahalli": 7.0,
        },
        "vehicle_counts": {
            "Bellandur": 3000, "Sarjapur": 2500,
        },
        "shelter_occupancies": {"S1": 4500, "S2": 2800, "S3": 2400, "S4": 3800, "S5": 1900},
        "zones_to_evacuate": [
            "Bellandur", "Sarjapur", "HSR Layout", "BTM Layout",
            "Koramangala", "Whitefield", "Electronic City", "Marathahalli"
        ],
    },
    # tick 5: receding — roads restore
    {
        "tick": 5,
        "zone_risk_scores": {
            "Bellandur": 4.0, "Sarjapur": 4.5, "Whitefield": 2.5,
            "HSR Layout": 3.5, "Koramangala": 3.0, "BTM Layout": 4.0,
            "Jayanagar": 2.0, "Rajajinagar": 1.0, "Hebbal": 1.5,
            "Yelahanka": 0.8, "Electronic City": 3.0, "Marathahalli": 2.5,
        },
        "vehicle_counts": {},
        "shelter_occupancies": {"S1": 4800, "S2": 2900, "S3": 2400, "S4": 4000, "S5": 1950},
        "zones_to_evacuate": ["Bellandur", "Sarjapur", "BTM Layout"],
    },
]


def run_test():
    print("=" * 70)
    print("  ADEO UIP17 — Mobility Agent Test (5 ticks)")
    print("=" * 70)

    integration = MobilityIntegration()

    for tick_data in TICKS:
        tick = tick_data["tick"]
        print(f"\n{'─'*70}")
        print(f"  TICK {tick}")
        print(f"{'─'*70}")

        result = integration.on_tick(tick, tick_data)
        summary = result["summary"]

        print(f"  Routes — OK: {summary['routes_ok']}  "
              f"Degraded: {summary['routes_degraded']}  "
              f"Failed: {summary['routes_failed']}")
        print(f"  Edges removed ({summary['edges_removed_count']}): "
              f"{', '.join(summary['removed_roads']) or 'none'}")

        print(f"\n  Zone Routes:")
        for zone, route in result["routes"].items():
            if route["status"] == "failed":
                print(f"    ✗  {zone:<20} FAILED — {route['reason'][:60]}")
            else:
                path_str = " → ".join(route["path"])
                print(
                    f"    {'✓' if route['status'] == 'ok' else '⚠'}  "
                    f"{zone:<20} {path_str}  "
                    f"[{route['total_distance_km']} km | "
                    f"quality={route['route_quality']:.2f}]"
                )

    print(f"\n{'='*70}")
    print("  Test complete. Logs written to data/mobility_logs.json")
    print(f"{'='*70}\n")

    # Show log summary
    all_logs = integration.get_logs()
    events = {}
    for log in all_logs:
        events[log["event"]] = events.get(log["event"], 0) + 1
    print("  Log summary:")
    for event, count in sorted(events.items()):
        print(f"    {event:<25} {count} entries")


if __name__ == "__main__":
    run_test()
