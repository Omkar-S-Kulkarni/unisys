import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from agents.mobility_agent.mobility_agent import MobilityAgent
from decision_governor.decision_governor import DecisionGovernor
from agents.vulnerability_agent.vulnerability_agent import calculate_zone_vulnerability
from agents.risk_agent import RiskForecastAgent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "active", "service": "ADEO API", "simulation_tick": simulation_state["tick"]}

_ROOT = os.path.dirname(os.path.dirname(__file__))

with open(os.path.join(_ROOT, "config.json")) as _f:
    config = json.load(_f)

with open(os.path.join(_ROOT, "agents", "vulnerability_agent", "data", "city_model.json")) as _f:
    city_model = json.load(_f)

mobility_agent = MobilityAgent()
decision_governor = DecisionGovernor(config=config, city_model=city_model)
risk_agent = RiskForecastAgent(os.path.join(_ROOT, "agents", "data"))

vulnerability_scores = {}
for z in city_model["zones"]:
    result = calculate_zone_vulnerability(z)
    vulnerability_scores[z["name"]] = result.vulnerability_score

clients = set()

simulation_state = {
    "tick": 0,
    "isRunning": False, # start paused
    "scenario": "moderate_flood",
    "manual_step": False
}

async def simulation_loop():
    while True:
        # Check if we should run this tick
        should_run = simulation_state["isRunning"] or simulation_state["manual_step"]
        
        if should_run:
            simulation_state["tick"] += 1
            simulation_state["manual_step"] = False # reset if it was a step
            tick = simulation_state["tick"]
            scenario = simulation_state["scenario"]

            zones = [
                "Bellandur", "Sarjapur", "Whitefield", "HSR Layout", "Koramangala",
                "BTM Layout", "Jayanagar", "Rajajinagar", "Hebbal", "Yelahanka",
                "Electronic City", "Marathahalli"
            ]
            
            # 1. Generate risk scores (from RiskForecastAgent)
            risk_scores = risk_agent.get_risk_scores(tick, scenario, city_model["zones"])

            # 2. Update Mobility Agent
            tick_data = mobility_agent.update_tick(
                tick,
                risk_scores,
                zones_to_evacuate=zones
            )

            # 3. Build zone_states
            zone_states = []
            zone_lookup = {z["name"]: z for z in city_model["zones"]}
            for zone_name in zones:
                base = dict(zone_lookup.get(zone_name, {"id": "?", "name": zone_name}))
                base["risk_score"] = risk_scores.get(zone_name, 0.0)
                base["vulnerability_score"] = vulnerability_scores.get(zone_name, 0.0)
                zone_states.append(base)

            # 4. Check Replan Triggers
            replan_triggered = False
            replan_trigger = None
            
            #   Condition A: Risk threshold exceeded
            threshold = config["decision_governor"].get("risk_threshold_for_replan", 7.5)
            if not replan_triggered:
                for zs in zone_states:
                    if zs["risk_score"] >= threshold:
                        replan_triggered = True
                        replan_trigger = {"trigger_type": "risk_threshold", "affected_zone_id": zs["id"], "tick": tick}
                        break
            
            #   Condition B: Route failed (from tick_data routes loop)
            if not replan_triggered:
                available_routes = tick_data.get("routes", {})
                for z_name, route_res in available_routes.items():
                    if route_res.get("status") == "failed":
                        replan_triggered = True
                        z_id = zone_lookup.get(z_name, {}).get("id", z_name)
                        replan_trigger = {"trigger_type": "route_flooded", "affected_zone_id": z_id, "tick": tick}
                        break

            #   Condition C: Shelter reaches 90% capacity
            if not replan_triggered:
                # Estimate shelter occupancy from the last plan + model base
                last_plan = decision_governor.get_last_plan()
                if last_plan:
                    shelter_usage = {s["id"]: s.get("current_occupancy", 0) for s in city_model.get("shelters", [])}
                    for seq in last_plan.get("evacuation_sequence", []):
                        sh = seq.get("assigned_shelter")
                        if sh:
                            shelter_usage[sh] = shelter_usage.get(sh, 0) + 1
                            
                    # check capacity limits
                    for s in city_model.get("shelters", []):
                        occ = shelter_usage.get(s["id"], 0)
                        cap = s.get("capacity", 1)
                        if occ / cap >= 0.9:
                            replan_triggered = True
                            replan_trigger = {"trigger_type": "shelter_full", "affected_zone_id": s["id"], "tick": tick}
                            break

            # 5. Run Decision Governor
            evac_plan = decision_governor.on_tick({
                "tick": tick,
                "zone_states": zone_states,
                "available_routes": tick_data.get("routes"),
                "replan_triggered": replan_triggered,
                "replan_trigger": replan_trigger,
            })

            # 6. Broadcast to clients
            combined_payload = {
                **tick_data,
                "evacuation_plan": evac_plan,
                "risk_scores": risk_scores,
                "zone_states": [
                    {
                        "zone_id": zs["id"],
                        "zone_name": zs["name"],
                        "risk_score": zs["risk_score"],
                        "vulnerability_score": zs["vulnerability_score"],
                        "elderly_pct": zs.get("elderly_pct", 0),
                        "elevation_tier": zs.get("elevation_tier", "mid"),
                    }
                    for zs in zone_states
                ],
                "simulation_state": simulation_state
            }

            if clients:
                message = json.dumps({"type": "TICK_UPDATE", "payload": combined_payload})
                disconnected = set()
                for client in clients:
                    try:
                        await client.send_text(message)
                    except Exception:
                        disconnected.add(client)
                clients.difference_update(disconnected)

        await asyncio.sleep(2) 

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(simulation_loop())

@app.get("/api/city-model")
async def get_city_model():
    return city_model

@app.get("/api/evacuation-plan")
async def get_evacuation_plan():
    plan = decision_governor.get_last_plan()
    if plan is None:
        return {"status": "no_plan_yet", "message": "Simulation has not produced a plan yet."}
    return plan

@app.get("/api/simulation-summary")
async def get_simulation_summary():
    from decision_governor.summary_generator import generate_summary
    log = decision_governor.get_simulation_log()
    return generate_summary(log)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    
    # Send initial state on connect
    await websocket.send_text(json.dumps({
        "type": "STATE_SYNC",
        "payload": {"simulation_state": simulation_state}
    }))
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message["type"] == "PAUSE_SIMULATION":
                simulation_state["isRunning"] = False
            elif message["type"] == "PLAY_SIMULATION" or message["type"] == "RESUME_SIMULATION":
                simulation_state["isRunning"] = True
            elif message["type"] == "STEP_SIMULATION":
                simulation_state["manual_step"] = True
            elif message["type"] == "CHANGE_SCENARIO":
                simulation_state["scenario"] = message.get("payload", "moderate_flood")
                # Reset tick on scenario change
                simulation_state["tick"] = 0
                simulation_state["isRunning"] = False
            elif message["type"] == "MANUAL_BLOCK":
                payload = message.get("payload", {})
                mobility_agent.mark_road_blocked(
                    payload.get("from"),
                    payload.get("to"),
                    payload.get("reason", "Manual Override via Dashboard")
                )
    except WebSocketDisconnect:
        clients.discard(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
