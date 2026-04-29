# Decision Governor Module

**ADEO UIP17 | Rohan (Decision Governor)**

Central evacuation decision engine for the Bengaluru flood disaster response simulation. Prioritises zones, assigns routes and shelters, generates human-readable rationale, and produces post-simulation summaries.

---

## Files

| File | Purpose |
|---|---|
| `decision_governor.py` | Core `DecisionGovernor` class — priority scoring, zone ranking, evacuation plan generation, replanning, simulation tick integration |
| `rationale_generator.py` | Human-readable rationale builder — 1–3 sentence explanations per zone decision |
| `summary_generator.py` | Post-event summary generator — aggregates tick data into final metrics |
| `city_model_schema.json` | Master inter-agent JSON schema contract with verified field sources |
| `__init__.py` | Package entry point, re-exports `DecisionGovernor` |
| `README.md` | This file — integration documentation |

---

## Quick Start

```python
import json
from decision_governor import DecisionGovernor

# Load config and city model
with open("config.json") as f:
    config = json.load(f)
with open("agents/vulnerability_agent/data/city_model.json") as f:
    city_model = json.load(f)

governor = DecisionGovernor(config=config, city_model=city_model)
```

---

## Integration Points

### Called by: Simulation Engine (`backend/main.py`)

```python
from decision_governor import DecisionGovernor

governor = DecisionGovernor(config=config, city_model=city_model)

# Each tick:
plan = governor.on_tick({
    "tick": tick_number,
    "zone_states": zones_with_runtime_scores,   # list of zone dicts
    "available_routes": mobility_result["routes"],  # from MobilityAgent
    "replan_triggered": False,
    "replan_trigger": None,
})
```

### Consumes from: Risk Agent (Omkar)

Zone risk scores (0–10 float) injected per tick into `zone_states[].risk_score`.

Currently simulated in `backend/main.py` (Risk Agent class is a placeholder).

### Consumes from: Vulnerability Agent (Disha)

Vulnerability scores (0–10 float) from `vulnerability_agent.py`:
- Function: `calculate_zone_vulnerability(zone)` → `ZoneScore`
- Key field: `vulnerability_score` (on `ZoneScore` dataclass)
- Input keys: `zone["id"]`, `zone["name"]`, `zone["elderly_pct"]`, `zone["population_density"]`, `zone["hospital_count"]`

### Consumes from: Mobility Agent (Vivek)

Route data from `MobilityAgent.update_tick()` or `MobilityIntegration.on_tick()`:
```python
{
    "tick": int,
    "routes": {
        "Bellandur": {
            "path": ["Bellandur", "Marathahalli", "Hebbal", "S03"],
            "total_distance_km": 18.3,
            "route_quality": 0.72,
            "status": "ok"    # "ok" | "degraded" | "failed"
        }
    },
    "removed_edges": [["Bellandur", "Sarjapur", "Sarjapur Road"]],
    "summary": { ... },
    "logs": [ ... ]
}
```

### Returns to: Frontend Dashboard (Disha)

Evacuation plan emitted via WebSocket as:
```json
{
    "type": "TICK_UPDATE",
    "payload": {
        "tick": 3,
        "evacuation_sequence": [
            {
                "rank": 1,
                "zone_id": "Z07",
                "zone_name": "Bellandur",
                "priority_score": 7.34,
                "assigned_route": { ... },
                "assigned_shelter": "S01",
                "rationale": "Zone Bellandur ranked 1st for evacuation: ..."
            }
        ],
        "timestamp": "2026-04-17T04:35:26+00:00"
    }
}
```

The frontend listens for `data.type === 'TICK_UPDATE'` in:
- `Orchestration.jsx` (line 50)
- `RoutePlan.jsx` (line 89)

---

## Config Reference (`config.json`)

```json
{
  "decision_governor": {
    "priority_weights": {
      "w_risk": 0.4,
      "w_vulnerability": 0.3,
      "w_elderly": 0.2,
      "w_road_availability": 0.1
    },
    "replan_cooldown_ticks": 2,
    "max_shelter_capacity_pct": 0.9,
    "risk_threshold_for_replan": 7.5
  }
}
```

All weights and thresholds are loaded from this config at construction time.
No values are hardcoded in the Python source.

---

## Priority Score Formula

```
priority = (
    w_risk             * risk_score          +    # 0–10
    w_vulnerability    * vulnerability_score +    # 0–10
    w_elderly          * (elderly_pct / 10)  +    # normalised to 0–10
    w_road_availability * road_availability       # 0.0 or 1.0
)
```

---

## Data Sources

| Data File | Owner | Key Fields Used |
|---|---|---|
| `agents/vulnerability_agent/data/city_model.json` | Disha | `zones[].id`, `.name`, `.population`, `.elderly_pct`, `.population_density`, `.elevation_tier`, `.hospital_count`, `.hospitals`, `.shelters`, `.shelter_capacity_total`, `.flood_risk_base` |
| `frontend/src/data/road_adjacency.json` | Vivek | `edges[].from`, `.to`, `.road_name`, `.capacity`, `.flood_risk_threshold`, `.distance_km` ; `shelters[].id`, `.name`, `.zone`, `.capacity` |
| `city_model.json → shelters[]` | Disha | `.id`, `.name`, `.zone_id`, `.capacity`, `.current_occupancy`, `.has_medical` |
| `config.json` | Rohan | `decision_governor.priority_weights.*`, `.replan_cooldown_ticks`, `.max_shelter_capacity_pct`, `.risk_threshold_for_replan` |

---

## Logging

Uses Python stdlib `logging.getLogger("DecisionGovernor")` — matching the convention used by `MobilityAgent` (`logging.getLogger("MobilityAgent")`).

Log format: `[DecisionGovernor][tick=N] message`

Logged events:
- Each tick: zone rankings + top 3 priority zones
- Each replan: trigger type, affected zone, cooldown status
- Each shelter assignment per zone
- Summary generation completion

---

## Edge Cases Handled

| Scenario | Behaviour |
|---|---|
| All shelters at capacity | `assigned_shelter: null`, rationale flags it |
| No usable route exists | `assigned_route: null`, zone still in plan |
| Agent data missing for a tick | Uses last known valid state, logs warning |
| Replan during cooldown | Returns last valid plan, logs skip reason |
| Empty simulation log | Returns zeroed summary dict |
