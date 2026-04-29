# Agent Contracts Quick Reference

## How to Use agent_contracts.json

### For Developers: Understanding Agent Output Contracts

---

## 1. Risk Agent Output Contract

**Where it's defined:**
- Schema: [schemas/agent_contracts.json](schemas/agent_contracts.json#L7) - `risk_agent_output`
- Code: [agents/risk_agent.py](agents/risk_agent.py#L56-L76) - `get_risk_scores()`

**What it returns:**
```python
# Simple dict: zone_name → risk_score (0-10 float)
{
    "Whitefield": 3.0,
    "Koramangala": 4.0,
    "HSR Layout": 4.5,
    "Sarjapur": 6.0,
    "Indiranagar": 2.0,
    ...
}
```

**How to use it:**
```python
from agents.risk_agent import RiskForecastAgent

risk_agent = RiskForecastAgent()
risk_scores = risk_agent.get_risk_scores(
    tick=1,
    scenario_type="moderate_flood",
    city_model_zones=city_model["zones"]
)

# Each zone gets a score - higher = more dangerous
for zone_name, score in risk_scores.items():
    print(f"{zone_name}: {score}/10")
```

**Used by:**
- ➜ Mobility Agent (to block flooded roads)
- ➜ Decision Governor (to rank zones)

---

## 2. Vulnerability Agent Output Contract

**Where it's defined:**
- Schema: [schemas/agent_contracts.json](schemas/agent_contracts.json#L33) - `vulnerability_agent_output`
- Code: [agents/vulnerability_agent/vulnerability_agent.py](agents/vulnerability_agent/vulnerability_agent.py#L88-L135) - `run_vulnerability_sweep()`

**What it returns:**
```python
# List of zones ranked by vulnerability
[
    {
        "zone_id": "Z01",
        "zone_name": "Bellandur",
        "vulnerability_score": 4.8,
        "rank": 1,
        "breakdown": {
            "elderly_impact": 0.45,
            "density_impact": 0.38,
            "hospital_gap": 0.0
        },
        "alerts": ["high_elderly_pop", "high_density_zone"]
    },
    ...  # 12 zones total
]
```

**How to use it:**
```python
from agents.vulnerability_agent.vulnerability_agent import (
    run_vulnerability_sweep,
    calculate_zone_vulnerability
)

# Full sweep (used at startup)
all_zones = run_vulnerability_sweep("city_model.json", mode="synthetic")

# Or for single zone
zone_score = calculate_zone_vulnerability(zone_dict)
print(f"{zone_score.zone_name}: {zone_score.vulnerability_score}")
```

**Used by:**
- ➜ Decision Governor (in priority calculation: `priority = w_risk*risk + w_vulnerability*vuln + ...`)

---

## 3. Mobility Agent Output Contract

**Where it's defined:**
- Schema: [schemas/agent_contracts.json](schemas/agent_contracts.json#L65) - `mobility_agent_output`
- Code: [agents/mobility_agent/mobility_agent.py](agents/mobility_agent/mobility_agent.py#L401-L470) - `update_tick()`

**What it returns:**
```python
{
    "tick": 1,
    "routes": {
        "Bellandur": {
            "tick": 1,
            "from_zone": "Bellandur",
            "to_zone": "S03",
            "path": ["Bellandur", "Marathahalli", "Whitefield", "S03"],
            "edges_used": [...],
            "total_distance_km": 21.1,
            "congestion_score": 0.45,    # 0 = free flow, 1 = gridlock
            "route_quality": 0.93,        # 0 = unusable, 1 = perfect
            "status": "ok",               # "ok" | "degraded" | "failed"
            "reason": ""
        },
        "Sarjapur": {
            "status": "failed",
            "reason": "No reachable shelters from Sarjapur — all full or flooded out."
        },
        ...
    },
    "removed_edges": [
        ["HSR Layout", "Bellandur", "HSR - Bellandur Road"],
        ...
    ],
    "logs": [...],
    "summary": {
        "tick": 1,
        "total_zones": 12,
        "routes_ok": 3,
        "routes_degraded": 0,
        "routes_failed": 0,
        "edges_removed_count": 0
    }
}
```

**How to use it:**
```python
from agents.mobility_agent.mobility_agent import MobilityAgent

agent = MobilityAgent()
result = agent.update_tick(
    tick=1,
    risk_scores={"Bellandur": 5.5, "Sarjapur": 6.0, ...},
    zones_to_evacuate=["Bellandur", "Sarjapur", ...]
)

# Check which zones can reach shelters
for zone_name, route in result["routes"].items():
    if route["status"] == "ok":
        print(f"✓ {zone_name} → {route['to_zone']} ({route['total_distance_km']} km)")
    else:
        print(f"✗ {zone_name}: {route['reason']}")
```

**Used by:**
- ➜ Decision Governor (to assign shelters and routes)
- ➜ Frontend UI (to display evacuation paths)

---

## 4. Decision Governor Output Contract

**Where it's defined:**
- Schema: [schemas/agent_contracts.json](schemas/agent_contracts.json#L142) - `governor_output`
- Code: [decision_governor/decision_governor.py](decision_governor/decision_governor.py#L298-L372) - `generate_evacuation_plan()`

**What it returns:**
```python
{
    "tick": 1,
    "evacuation_sequence": [
        {
            "rank": 1,
            "zone_id": "Z01",
            "zone_name": "Bellandur",
            "priority_score": 5.36,
            "assigned_route": {
                "tick": 1,
                "from_zone": "Bellandur",
                "to_zone": "S03",
                "path": ["Bellandur", "Marathahalli", "Whitefield", "S03"],
                "total_distance_km": 21.1,
                "congestion_score": 0.45,
                "route_quality": 0.93,
                "status": "ok"
            },
            "assigned_shelter": "S03",
            "rationale": "Zone Bellandur ranked 1st for evacuation: risk score 9.0/10..."
        },
        {
            "rank": 2,
            "zone_id": "Z02",
            "zone_name": "Sarjapur",
            "priority_score": 4.76,
            "assigned_route": null,
            "assigned_shelter": "S01",
            "rationale": "Zone Sarjapur ranked 2nd: risk score 7.5/10..."
        },
        ...  # 12 zones total
    ],
    "timestamp": "2026-04-28T14:04:00.305767+00:00"
}
```

**How to use it:**
```python
from decision_governor.decision_governor import DecisionGovernor

gov = DecisionGovernor(config=config, city_model=city_model)
plan = gov.on_tick({
    "tick": 1,
    "zone_states": zone_states_with_risk_vulnerability,
    "available_routes": mobility_routes,
    "replan_triggered": False
})

# Process evacuation sequence
for entry in plan["evacuation_sequence"]:
    print(f"Rank {entry['rank']}: {entry['zone_name']}")
    print(f"  Priority: {entry['priority_score']}")
    print(f"  Shelter: {entry['assigned_shelter']}")
    print(f"  Reason: {entry['rationale']}")
```

**Used by:**
- ➜ Frontend UI (via WebSocket in backend/main.py)
- ➜ Simulation engine (to track evacuation status)

---

## 5. Data Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ TICK START                                                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
        ┌──────────────────────────────────────┐
        │ Risk Agent.get_risk_scores()         │
        │ OUTPUT: {zone: 0-10}                 │
        └──────────────────────────────────────┘
              ↓ (used to block roads)
        ┌──────────────────────────────────────┐
        │ Mobility Agent.update_tick()         │
        │ INPUT: risk_scores                   │
        │ OUTPUT: {routes, removed_edges, ...} │
        └──────────────────────────────────────┘
              ↓ (used to assign shelters)
        ┌──────────────────────────────────────┐
        │ Decision Governor.on_tick()          │
        │ INPUT: routes, risk_scores, vuln     │
        │ OUTPUT: evacuation_sequence          │
        └──────────────────────────────────────┘
              ↓
        ┌──────────────────────────────────────┐
        │ Send to Frontend via WebSocket        │
        │ TYPE: TICK_UPDATE                    │
        │ PAYLOAD: All agent outputs combined  │
        └──────────────────────────────────────┘
```

---

## 6. Common Patterns

### Pattern 1: Accessing Route for a Zone
```python
# From mobility agent output
routes = mobility_result["routes"]
route = routes.get("Bellandur")

if route and route["status"] == "ok":
    print(f"Path: {' → '.join(route['path'])}")
    print(f"Distance: {route['total_distance_km']} km")
    print(f"Quality: {route['route_quality']*100}%")
else:
    print(f"Route failed: {route['reason']}")
```

### Pattern 2: Extracting Priorities
```python
# From decision governor output
for entry in evac_plan["evacuation_sequence"]:
    priority_score = entry["priority_score"]
    
    if priority_score >= 5.0:
        tier = "CRITICAL"
    elif priority_score >= 4.0:
        tier = "HIGH"
    else:
        tier = "MEDIUM"
    
    print(f"{entry['zone_name']}: {tier} (score: {priority_score})")
```

### Pattern 3: Checking Shelter Assignment
```python
# From decision governor output
shelter_id = entry["assigned_shelter"]

if shelter_id:
    # Find shelter details
    shelter = next(s for s in city_model["shelters"] if s["id"] == shelter_id)
    print(f"→ {shelter['name']} ({shelter_id})")
else:
    print("→ NO SHELTER (all at capacity or inaccessible)")
```

### Pattern 4: Processing Failure Reasons
```python
# From mobility agent output
for zone_name, route in routes.items():
    if route["status"] == "failed":
        # Zone cannot reach any shelter
        # Trigger replanning
        print(f"REPLANNING: {zone_name} - {route['reason']}")
```

---

## 7. Shelter IDs (Unified Format)

All shelters use **S01, S02, S03** format (consistent across all agents):

| ID | Name | Zone | Capacity |
|----|----|------|----------|
| **S01** | RMC Ground Hebbal | Hebbal | 1000 |
| **S02** | Kanteerava Stadium CBD | Yelahanka | 500 |
| **S03** | ITPL Convention Centre | Whitefield | 1000 |

**Never use**: S1, S2, S3, S-1, S_01, etc.

---

## 8. Validation Checklist for New Agents

When adding a new agent, verify:

- [ ] Output structure matches schema in agent_contracts.json
- [ ] All numeric scores are normalized (0–1 or 0–10)
- [ ] All IDs follow project format (zone IDs, shelter IDs)
- [ ] All timestamps are ISO 8601
- [ ] Required fields are always present
- [ ] No unknown additional fields
- [ ] Data types are correct (int, float, string, array, object)
- [ ] Enums use exact values (e.g., "ok" not "OK")
- [ ] Output tested against schema validator
- [ ] Integration test shows data flows to next agent

---

## 9. Running Tests

```bash
# Test Mobility Agent
python test_mobility_agent.py

# Test Decision Governor
cd ADEO_UIP17
python test_decision_governor.py

# Validate schema
python -c "import json; json.load(open('schemas/agent_contracts.json'))"

# Run all Python syntax checks
python -m py_compile agents/risk_agent.py \
                       agents/vulnerability_agent/vulnerability_agent.py \
                       agents/mobility_agent/mobility_agent.py \
                       decision_governor/decision_governor.py
```

---

## 10. Key Files

| File | Purpose |
|------|---------|
| [schemas/agent_contracts.json](schemas/agent_contracts.json) | Master schema definition |
| [agents/risk_agent.py](agents/risk_agent.py) | Risk scoring (input: city model, output: risk dict) |
| [agents/vulnerability_agent/vulnerability_agent.py](agents/vulnerability_agent/vulnerability_agent.py) | Vulnerability ranking (input: city model, output: array) |
| [agents/mobility_agent/mobility_agent.py](agents/mobility_agent/mobility_agent.py) | Route planning (input: risk scores, output: routes dict) |
| [decision_governor/decision_governor.py](decision_governor/decision_governor.py) | Evacuation planning (input: risk+vulnerability+routes, output: sequence) |
| [backend/main.py](backend/main.py) | Integration orchestrator (orchestrates all agents) |
| [AGENT_CONTRACTS_VALIDATION.md](AGENT_CONTRACTS_VALIDATION.md) | Full validation report |

---

## Need Help?

**Schema questions?** → See [AGENT_CONTRACTS_VALIDATION.md](AGENT_CONTRACTS_VALIDATION.md)  
**Implementation issues?** → Check [test_mobility_agent.py](test_mobility_agent.py) or [test_decision_governor.py](test_decision_governor.py)  
**Data format?** → Verify against [schemas/agent_contracts.json](schemas/agent_contracts.json)  
