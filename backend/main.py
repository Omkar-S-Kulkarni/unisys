import sys
import os
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import json
import random
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from agents.mobility_agent.mobility_agent import MobilityAgent
from decision_governor.decision_governor import DecisionGovernor
from agents.vulnerability_agent.vulnerability_agent import calculate_zone_vulnerability, run_vulnerability_sweep
from agents.risk_agent import RiskForecastAgent
from agents.ollama_client import OllamaClient
from decision_governor import rationale_generator as rg
from decision_governor import summary_generator as sg
from schema_validator import (
    load_contracts_schema,
    get_contract_subschema,
    validate_payload,
)
from twilio.rest import Client

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("ADEOBackend")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s][%(levelname)s][tick=%(tick)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _log_validation_errors(source: str, errors: list[dict], tick: int = 0) -> None:
    for err in errors:
        path = ".".join(str(p) for p in err.get("path", [])) or "<root>"
        logger.error(
            f"Validation failed for {source}: {err['message']} at {path}",
            extra={"tick": tick},
        )


@app.get("/")
async def root():
    return {"status": "active", "service": "ADEO API", "simulation_tick": simulation_state["tick"]}

_ROOT = os.path.dirname(os.path.dirname(__file__))

with open(os.path.join(_ROOT, "config.json")) as _f:
    config = json.load(_f)

with open(os.path.join(_ROOT, "agents", "vulnerability_agent", "data", "city_model.json")) as _f:
    city_model = json.load(_f)

SCHEMA_PATH = os.path.join(_ROOT, "schemas", "agent_contracts.json")
contracts_schema = load_contracts_schema(SCHEMA_PATH)
risk_schema = get_contract_subschema(contracts_schema, "risk_agent_output")
vuln_schema = get_contract_subschema(contracts_schema, "vulnerability_agent_output")
mobility_schema = get_contract_subschema(contracts_schema, "mobility_agent_output")
llm_risk_schema = get_contract_subschema(contracts_schema, "risk_agent_llm_output")
governor_schema = get_contract_subschema(contracts_schema, "governor_output")

# ── Initialize Ollama Client ──────────────────────────────────────────────────
ollama_config = config.get("ollama", {})
ollama_client = OllamaClient(
    host=ollama_config.get("host", "http://127.0.0.1:11434"),
    model=ollama_config.get("model", "llama3.2:3b"),
    fallback_model=ollama_config.get("fallback_model", "qwen2.5-coder:7b"),
    timeout=ollama_config.get("timeout_seconds", 30),
    cache_ttl=ollama_config.get("cache_ttl_seconds", 30),
    enabled=ollama_config.get("enabled", True),
)

# Inject Ollama client into all modules that need it
rg.set_ollama_client(ollama_client)
sg.set_ollama_client(ollama_client)

# ── Initialize Agents ─────────────────────────────────────────────────────────
mobility_agent = MobilityAgent()
decision_governor = DecisionGovernor(config=config, city_model=city_model)
risk_agent = RiskForecastAgent(os.path.join(_ROOT, "agents", "data"), ollama_client=ollama_client)

# ── Initialize Twilio Client ──────────────────────────────────────────────────
twilio_config = config.get("twilio", {})
twilio_enabled = twilio_config.get("enabled", False)
if twilio_enabled:
    twilio_client = Client(twilio_config["account_sid"], twilio_config["auth_token"])
else:
    twilio_client = None

async def send_twilio_notification(zone_name, safety_score, shelter_name, route_name):
    if not twilio_client:
        logger.info(f"Twilio disabled. Simulated notification for {zone_name}: Score {safety_score}/10, Shelter: {shelter_name}, Route: {route_name}")
        return True
    
    try:
        message_body = (
            f"ADEO EMERGENCY ALERT: {zone_name}\n"
            f"Safety Score: {safety_score}/10\n"
            f"Nearest Shelter: {shelter_name}\n"
            f"Safest Route: {route_name}\n"
            f"Please proceed to the shelter immediately."
        )
        
        message = twilio_client.messages.create(
            body=message_body,
            from_=twilio_config["from_number"],
            to=twilio_config["to_number"]
        )
        logger.info(f"Twilio message sent to {twilio_config['to_number']} for {zone_name}: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Twilio message for {zone_name}: {str(e)}")
        return False


# ── WebSocket Clients ────────────────────────────────────────────────────────
clients = set()

simulation_state = {
    "tick": 0,
    "isRunning": False, 
    "scenario": "severe_flood",
    "manual_step": False,
    "manual_replan_requested": False,
    "replan_events": [],
    "evacuated_zones": [],
    "evacuation_complete": False,
    "evacuated_population": {}, # zone_name -> count
    "zone_evacuation_steps": {}, # zone_name -> steps_count
}

# Store the latest LLM analysis for API access
_latest_llm_analysis: dict = {}
_latest_llm_rationales: dict = {}

async def simulation_loop():
    global _latest_llm_analysis, _latest_llm_rationales
    while True:
        # Check if we should run this tick
        should_run = simulation_state["isRunning"] or simulation_state["manual_step"]
        
        if should_run:
            simulation_state["tick"] += 1
            simulation_state["manual_step"] = False # reset if it was a step
            tick = simulation_state["tick"]
            scenario = simulation_state["scenario"]

            zones = [
                "Whitefield", "Koramangala", "HSR Layout", "Sarjapur", "Indiranagar",
                "Mahadevapura", "Bellandur", "Marathahalli", "BTM Layout", "Electronic City",
                "Hebbal", "Yelahanka"
            ]
            
            # 1. Generate risk scores (from RiskForecastAgent — rule-based baseline)
            risk_scores = risk_agent.get_risk_scores(tick, scenario, city_model["zones"])
            
            # Update avg risk
            simulation_state["avg_risk"] = sum(risk_scores.values()) / len(risk_scores) if risk_scores else 0
            
            # Validate Risk Output
            is_valid_risk, risk_errors = validate_payload(risk_schema, risk_scores)
            if not is_valid_risk:
                _log_validation_errors("Risk Agent", risk_errors, tick)
                # If invalid, we continue but log the rejection
                logger.error(f"Tick {tick}: Risk output REJECTED due to validation errors", extra={"tick": tick})

            # 1b. Fire LLM risk analysis asynchronously (non-blocking)
            llm_analysis_task = asyncio.create_task(
                risk_agent.get_llm_risk_analysis(tick, scenario, city_model["zones"], risk_scores)
            )

            # 2. Update Mobility Agent with live shelter occupancy
            shelter_occupancies = {s["id"]: s.get("current_occupancy", 0) for s in city_model.get("shelters", [])}
            tick_data = mobility_agent.update_tick(
                tick,
                risk_scores,
                zones_to_evacuate=zones,
                shelter_occupancies=shelter_occupancies
            )

            # Validate Mobility Output
            is_valid_mobility, mobility_errors = validate_payload(mobility_schema, tick_data)
            if not is_valid_mobility:
                _log_validation_errors("Mobility Agent", mobility_errors, tick)
                logger.error(f"Tick {tick}: Mobility output REJECTED due to validation errors", extra={"tick": tick})

            # 3. Run Vulnerability Sweep (Dynamic per tick as per Phase 8)
            vulnerability_sweep = run_vulnerability_sweep(
                os.path.join(_ROOT, "agents", "vulnerability_agent", "data", "city_model.json"),
                mode="synthetic"
            )
            
            # Validate Vulnerability Output
            is_valid_vuln, vuln_errors = validate_payload(vuln_schema, vulnerability_sweep)
            if not is_valid_vuln:
                _log_validation_errors("Vulnerability Agent", vuln_errors, tick)
                logger.error(f"Tick {tick}: Vulnerability output REJECTED due to validation errors", extra={"tick": tick})

            # 4. Build zone_states (Collecting all agent outputs)
            zone_states = []
            zone_lookup = {z["name"]: z for z in city_model["zones"]}
            vulnerability_map = {v["zone_name"]: v for v in vulnerability_sweep}
            
            for zone_name in zones:
                base = dict(zone_lookup.get(zone_name, {"id": "?", "name": zone_name}))
                base["risk_score"] = risk_scores.get(zone_name, 0.0)
                
                vuln_data = vulnerability_map.get(zone_name, {})
                base["vulnerability_score"] = vuln_data.get("vulnerability_score", 0.0)
                base["priority_tier"] = vuln_data.get("priority_tier", "Low")
                
                # Metadata for Decision Governor
                base["elderly_pct"] = base.get("elderly_pct", 0) 
                
                zone_states.append(base)

            # 5. Check Replan Triggers
            replan_triggered = False
            replan_trigger = None
            
            #   Condition A: Manual Emergency Replan (Phase 9)
            if simulation_state.get("manual_replan_requested", False):
                replan_triggered = True
                replan_trigger = {"trigger_type": "manual_emergency", "affected_zone_id": "ALL", "tick": tick}
                simulation_state["manual_replan_requested"] = False # Reset flag

            #   Condition B: Risk threshold exceeded
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

            #   Condition D: Shelter reaches 90% capacity (Phase 9)
            if not replan_triggered:
                # Estimate shelter occupancy from the last plan + model base
                last_plan = decision_governor.get_last_plan()
                if last_plan:
                    # Start with current city model occupancy
                    shelter_usage = {s["id"]: s.get("current_occupancy", 0) for s in city_model.get("shelters", [])}
                    
                    # Add populations of zones assigned in the last plan
                    for seq in last_plan.get("evacuation_sequence", []):
                        sh_id = seq.get("assigned_shelter")
                        z_id = seq.get("zone_id")
                        if sh_id and z_id:
                            zone_pop = zone_lookup.get(seq.get("zone_name"), {}).get("population", 0)
                            shelter_usage[sh_id] = shelter_usage.get(sh_id, 0) + zone_pop
                            
                    # check capacity limits
                    for s in city_model.get("shelters", []):
                        occ = shelter_usage.get(s["id"], 0)
                        cap = s.get("capacity", 1)
                        if occ / cap >= 0.9:
                            replan_triggered = True
                            replan_trigger = {
                                "trigger_type": "shelter_full", 
                                "affected_zone_id": s["id"], 
                                "tick": tick,
                                "details": f"Shelter {s['id']} projected at {round(occ/cap*100, 1)}% capacity"
                            }
                            break

            if replan_triggered and replan_trigger:
                replan_trigger["timestamp"] = datetime.now(timezone.utc).isoformat()
                simulation_state["replan_events"].append(replan_trigger)
                # Keep only last 50 events
                if len(simulation_state["replan_events"]) > 50:
                    simulation_state["replan_events"].pop(0)

            # 6. Apply emergency overrides if any
            overrides = simulation_state.get("emergency_overrides", {})
            if overrides:
                # Update shelter size
                if overrides.get("shelterSize"):
                    for s in city_model["shelters"]:
                        s["capacity"] = int(overrides["shelterSize"])
                
                # Modify zone_states for prioritize_zone
                if overrides.get("prioritizeZone"):
                    prioritized = overrides["prioritizeZone"]
                    zone_states = sorted(zone_states, key=lambda z: (z["name"] != prioritized, -z.get("priority_score", 0)))
                
                # Modify available_routes for change_path
                routes = tick_data.get("routes", {})
                if overrides.get("changePathFrom") and overrides.get("changePathTo"):
                    from_zone = overrides["changePathFrom"]
                    to_shelter = overrides["changePathTo"]
                    # Compute new route
                    new_route = mobility_agent.get_route(from_zone, to_shelter)
                    if new_route.status != "failed":
                        routes[from_zone] = {
                            "path": new_route.path,
                            "to_zone": to_shelter,
                            "total_distance_km": new_route.total_distance_km,
                            "congestion_score": new_route.congestion_score,
                            "route_quality": new_route.route_quality,
                            "status": new_route.status
                        }
                
                tick_data["routes"] = routes

            # Clear overrides after applying
            simulation_state["emergency_overrides"] = {}

            # 7. Run Decision Governor
            tick_state = {
                "tick": tick,
                "zone_states": zone_states,
                "available_routes": tick_data.get("routes"),
                "replan_triggered": replan_triggered,
                "replan_trigger": replan_trigger,
            }
            evac_plan = decision_governor.on_tick(tick_state)
            
            # Add next_batch_size to the plan for UI tracking
            for order in evac_plan.get("evacuation_sequence", []):
                z_n = order.get("zone_name")
                # We'll calculate this again in the loop, but we need a placeholder for the UI
                # or better, we set it AFTER the loop below.
                pass
            
            # 7. Generate candidate plans (strategic alternatives)
            candidate_plans = decision_governor.generate_candidate_plans(
                zone_states, 
                available_routes=tick_data.get("routes")
            )

            # Validate Governor Output
            is_valid_gov, gov_errors = validate_payload(governor_schema, evac_plan)
            if not is_valid_gov:
                _log_validation_errors("Decision Governor", gov_errors, tick)
                logger.error(f"Tick {tick}: Governor plan REJECTED due to validation errors", extra={"tick": tick})

            # 8. Await the LLM analysis result (should be done by now or will finish soon)
            try:
                llm_analysis = await asyncio.wait_for(llm_analysis_task, timeout=15.0)
                _latest_llm_analysis = llm_analysis or {}
                
                # Validate LLM Risk Output
                if _latest_llm_analysis:
                    is_valid_llm, llm_errors = validate_payload(llm_risk_schema, _latest_llm_analysis)
                    if not is_valid_llm:
                        _log_validation_errors("Risk Agent (LLM)", llm_errors, tick)
                        logger.error(f"Tick {tick}: LLM Risk analysis REJECTED due to validation errors", extra={"tick": tick})
            except (asyncio.TimeoutError, Exception) as e:
                _latest_llm_analysis = risk_agent.get_last_llm_analysis() or {}

            # 9. Fire LLM batch rationales asynchronously
            try:
                ranked_zones = evac_plan.get("evacuation_sequence", [])
                llm_rationales = await asyncio.wait_for(
                    rg.generate_batch_rationales(
                        ranked_zones,
                        tick_data.get("routes"),
                        city_model.get("shelters", []),
                    ),
                    timeout=15.0,
                )
                _latest_llm_rationales = llm_rationales
            except (asyncio.TimeoutError, Exception):
                _latest_llm_rationales = {}

            # Enrich evacuation plan entries with LLM data and batch info
            for entry in evac_plan.get("evacuation_sequence", []):
                z_name = entry.get("zone_name", "")

                # Add batch info for the top 3
                if z_name in [e.get("zone_name") for e in evac_plan.get("evacuation_sequence", [])[:3]]:
                    steps = simulation_state["zone_evacuation_steps"].get(z_name, 0)
                    # Use the same logic as step 10 to predict next batch
                    next_steps = steps + 1
                    if next_steps == 1: b = 100
                    elif next_steps == 2: b = 200
                    elif next_steps == 3: b = 250
                    else: b = 300 + (next_steps - 4) * 50
                    
                    total_pop = zone_lookup.get(z_name, {}).get("population", 0)
                    already_evac = simulation_state["evacuated_population"].get(z_name, 0)
                    entry["next_batch_size"] = min(b, total_pop - already_evac)
                else:
                    entry["next_batch_size"] = 0

                # Add LLM risk analysis
                if z_name in _latest_llm_analysis:
                    analysis = _latest_llm_analysis[z_name]
                    entry["llm_risk_reasoning"] = analysis.get("reasoning", "")
                    entry["llm_risk_level"] = analysis.get("risk_level", "")
                    entry["llm_recommendation"] = analysis.get("recommendation", "")
                    entry["analysis_source"] = analysis.get("source", "rule-based")

                # Add LLM rationale (override template if available)
                if z_name in _latest_llm_rationales:
                    entry["llm_rationale"] = _latest_llm_rationales[z_name]

            # 10. Update Shelter Occupancy & Evacuated Status (Phase 12) - INCREMENTAL
            newly_evacuated = []
            evacuation_updates = []
            for entry in evac_plan.get("evacuation_sequence", []):
                z_name = entry.get("zone_name")
                s_id = entry.get("assigned_shelter")
                has_route = entry.get("assigned_route") is not None
                
                if z_name and s_id and has_route and z_name not in simulation_state["evacuated_zones"]:
                    # Find shelter in city_model
                    s = None
                    for sh in city_model["shelters"]:
                        if sh["id"] == s_id:
                            s = sh
                            break
                    
                    if not s:
                        continue
                    
                    # Incremental Batch Logic
                    steps = simulation_state["zone_evacuation_steps"].get(z_name, 0)
                    steps += 1
                    simulation_state["zone_evacuation_steps"][z_name] = steps
                    
                    # Batch size: 100, 200, 250, 300... as requested
                    # Batch size: Starting at 5000 and increasing rapidly for large populations
                    # Batch size: Incremental to show progress
                    if steps == 1: batch_size = 5000
                    elif steps == 2: batch_size = 10000
                    elif steps == 3: batch_size = 15000
                    else: batch_size = 20000 + (steps - 4) * 5000
                    
                    total_pop = zone_lookup.get(z_name, {}).get("population", 0)
                    already_evac = simulation_state["evacuated_population"].get(z_name, 0)
                    remaining = total_pop - already_evac
                    
                    actual_move = min(batch_size, remaining)
                    
                    if actual_move <= 0:
                        continue
                    
                    # Ensure we don't overfill the current shelter
                    # We allow up to 5% overflow for emergencies
                    space_available = max(0, int(s["capacity"] * 1.05) - s.get("current_occupancy", 0))
                    
                    if space_available < actual_move:
                        # Current shelter cannot hold the full batch. 
                        # Try to find a new shelter if current is already very full.
                        if space_available < (batch_size * 0.1) or space_available == 0:
                            # Find new shelter: nearest available
                            available_shelters = []
                            for sh in city_model["shelters"]:
                                sh_space = max(0, int(sh["capacity"] * 1.05) - sh.get("current_occupancy", 0))
                                if sh_space > 0:
                                    route = mobility_agent.get_route(z_name, sh["id"])
                                    if route.status != "failed":
                                        available_shelters.append((sh, route, sh_space))
                            
                            if available_shelters:
                                # Sort by distance
                                available_shelters.sort(key=lambda x: x[1].total_distance_km)
                                new_sh, new_route, new_space = available_shelters[0]
                                s_id = new_sh["id"]
                                s = new_sh
                                space_available = new_space
                                # Update entry for plan
                                entry["assigned_shelter"] = s_id
                                # Update route in tick_data
                                tick_data["routes"][z_name] = {
                                    "path": new_route.path,
                                    "to_zone": s_id,
                                    "total_distance_km": new_route.total_distance_km,
                                    "congestion_score": new_route.congestion_score,
                                    "route_quality": new_route.route_quality,
                                    "status": new_route.status
                                }
                            else:
                                # No more shelters with space!
                                logger.warning(f"Tick {tick}: No shelter space available for {z_name}")
                        
                        # Re-cap actual_move by available space in the (possibly new) shelter
                        actual_move = min(actual_move, space_available)

                    if actual_move <= 0:
                        continue
                    
                    # Now move to the (possibly updated) shelter
                    s["current_occupancy"] += actual_move
                    simulation_state["evacuated_population"][z_name] = already_evac + actual_move
                    
                    # Log the shelter occupancy update
                    logger.info(f"Tick {tick}: Shelter {s_id} ({s['name']}) occupancy: {s['current_occupancy']} (from {z_name} evacuation)", extra={"tick": tick})
                    
                    # Update zone status in city_model
                    for z in city_model["zones"]:
                        if z["name"] == z_name:
                            z["remaining_population"] = total_pop - (already_evac + actual_move)
                            if z["remaining_population"] <= 0:
                                z["status"] = "evacuated"
                                if z_name not in simulation_state["evacuated_zones"]:
                                    simulation_state["evacuated_zones"].append(z_name)
                                    newly_evacuated.append(z_name)
                            else:
                                z["status"] = "partially_evacuated"
                                evacuation_updates.append(f"{z_name}: +{actual_move}")
                            
                            # Sync batch size back to the plan for UI
                            for order in evac_plan["evacuation_sequence"]:
                                if order.get("zone_name") == z_name:
                                    order["next_batch_size"] = actual_move
                            break
                    logger.info(f"Tick {tick}: {z_name} moved {actual_move} to {s_id} (Total: {already_evac + actual_move}/{total_pop})")

            # Calculate average risk for Post Analysis
            total_risk = sum(z.get("risk_score", 0) for z in city_model["zones"])
            avg_risk = total_risk / len(city_model["zones"]) if city_model["zones"] else 0
            simulation_state["avg_risk"] = avg_risk

            # Check if all zones are evacuated
            all_evacuated = all(z.get("status") == "evacuated" for z in city_model["zones"])
            if all_evacuated and not simulation_state["evacuation_complete"]:
                simulation_state["evacuation_complete"] = True
                logger.info(f"Tick {tick}: ALL ZONES FULLY EVACUATED. Simulation objective achieved.")

            # 11. Aggregate System Logs (Phase 10)
            system_logs = []
            # Add newly evacuated logs
            for z in newly_evacuated:
                system_logs.append({
                    "tick": tick,
                    "type": "evacuation_success",
                    "message": f"SUCCESS: {z} fully evacuated.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            # Add incremental evacuation logs
            for up in evacuation_updates:
                system_logs.append({
                    "tick": tick,
                    "type": "evacuation_update",
                    "message": f"IN PROGRESS: {up} citizens moving to shelter.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            # Add mobility logs
            system_logs.extend(tick_data.get("logs", []))
            # Add replan logs (last 5)
            for event in simulation_state["replan_events"][-5:]:
                system_logs.append({
                    "tick": event["tick"],
                    "type": "replan_event",
                    "message": f"REPLAN [{event['trigger_type']}] triggered for {event['affected_zone_id']}",
                    "timestamp": event["timestamp"]
                })
            
            # 12. Broadcast to clients
            combined_payload = {
                **tick_data,
                "system_logs": system_logs,
                "evacuation_plan": evac_plan,
                "candidate_plans": candidate_plans,
                "risk_scores": risk_scores,
                "zone_states": [
                    {
                        "zone_id": zs["id"],
                        "zone_name": zs["name"],
                        "risk_score": zs["risk_score"],
                        "vulnerability_score": zs["vulnerability_score"],
                        "priority_tier": zs.get("priority_tier", "Low"),
                        "elderly_pct": zs.get("elderly_pct", 0),
                        "elevation_tier": zs.get("elevation_tier", "mid"),
                    }
                    for zs in zone_states
                ],
                "replan_events": simulation_state["replan_events"],
                "simulation_state": simulation_state,
                "evacuated_zones_count": sum(1 for z in city_model["zones"] if z.get("status") == "evacuated"),
                "shelter_status": [
                    {
                        "id": s["id"],
                        "name": s["name"],
                        "current_occupancy": s.get("current_occupancy", 0),
                        "capacity": s.get("capacity", 0),
                        "available_capacity": max(s.get("capacity", 0) - s.get("current_occupancy", 0), 0),
                        "load_pct": round((s.get("current_occupancy", 0) / s.get("capacity", 1)) * 100, 1) if s.get("capacity", 0) > 0 else 0,
                    }
                    for s in city_model["shelters"]
                ],
                "llm_analysis": {
                    zone_name: {
                        "risk_level": data.get("risk_level", ""),
                        "reasoning": data.get("reasoning", ""),
                        "recommendation": data.get("recommendation", ""),
                        "source": data.get("source", "rule-based"),
                    }
                    for zone_name, data in _latest_llm_analysis.items()
                },
                "ollama_status": ollama_client.get_status(),
                "city_model": city_model,
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

@app.get("/api/simulation-summary")
async def get_simulation_summary():
    """
    Combined simulation summary endpoint.
    Returns both raw metrics and the LLM-enhanced narrative summary.
    """
    log = decision_governor.get_simulation_log()
    
    # Generate the detailed LLM/statistical summary
    summary_data = await sg.generate_llm_summary(log)
    
    # Inject real events from simulation state if not present
    formatted_events = []
    for ev in simulation_state.get("replan_events", []):
        formatted_events.append({
            "tick": ev.get("tick", 0),
            "message": f"REPLAN: {ev.get('trigger_type', 'Manual')} for {ev.get('affected_zone_id', 'ALL')}"
        })
    
    summary_data["events"] = formatted_events
    
    # Ensure metrics are up to date
    summary_data["metrics"] = {
        "total_ticks": simulation_state.get("tick", 0),
        "zones_evacuated": sum(1 for z in city_model["zones"] if z.get("status") == "evacuated"),
        "replan_count": len(simulation_state.get("replan_events", [])),
        "avg_risk": round(simulation_state.get("avg_risk", 0), 2)
    }
    
    return summary_data

@app.on_event("startup")
async def startup_event():
    # Check Ollama availability at startup
    available = await ollama_client.is_available()
    if available:
        models = await ollama_client.list_models()
        print(f"[ADEO] Ollama connected — active model: {ollama_client.active_model}, available: {models}")
    else:
        print("[ADEO] Ollama not available — running in rule-based fallback mode")
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

@app.get("/api/ollama-status")
async def get_ollama_status():
    """Returns the current Ollama connection status, models, and health."""
    status = ollama_client.get_status()
    status["available"] = await ollama_client.is_available()
    status["models"] = await ollama_client.list_models()
    return status

@app.get("/api/llm-analysis/{zone_name}")
async def get_llm_zone_analysis(zone_name: str):
    """
    On-demand LLM risk analysis for a specific zone.
    Returns cached analysis if available, otherwise generates fresh.
    """
    # Check cached analysis first
    if zone_name in _latest_llm_analysis:
        return {
            "zone_name": zone_name,
            "analysis": _latest_llm_analysis[zone_name],
            "source": "cached",
        }

    # Generate fresh analysis if Ollama is available
    if not await ollama_client.is_available():
        return {
            "zone_name": zone_name,
            "analysis": None,
            "error": "Ollama not available",
            "source": "unavailable",
        }

    # Get current risk scores
    tick = simulation_state["tick"]
    scenario = simulation_state["scenario"]
    risk_scores = risk_agent.get_risk_scores(tick, scenario, city_model["zones"])

    analysis = await risk_agent.get_llm_risk_analysis(
        tick, scenario, city_model["zones"], risk_scores
    )

    zone_analysis = analysis.get(zone_name)
    if zone_analysis:
        return {
            "zone_name": zone_name,
            "analysis": zone_analysis,
            "source": "fresh",
        }

    return {
        "zone_name": zone_name,
        "analysis": None,
        "error": "Zone not found in analysis",
        "source": "not_found",
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    
    # Send initial state on connect (include Ollama status)
    await websocket.send_text(json.dumps({
        "type": "STATE_SYNC",
        "payload": {
            "simulation_state": simulation_state,
            "ollama_status": ollama_client.get_status(),
        }
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
            elif message["type"] == "EMERGENCY_REPLAN":
                simulation_state["manual_replan_requested"] = True
                simulation_state["emergency_overrides"] = message.get("payload", {})
                logger.info("Manual EMERGENCY REPLAN requested via dashboard")
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
            elif message["type"] == "SEND_EMERGENCY_NOTIFICATIONS":
                # Get the latest evacuation plan
                last_plan = decision_governor.get_last_plan()
                if not last_plan:
                    continue
                
                notifications_sent = 0
                for entry in last_plan.get("evacuation_sequence", []):
                    z_name = entry.get("zone_name")
                    risk = entry.get("risk_score", 0.0)
                    # Safety score is 10 - risk score
                    safety_score = round(10.0 - risk, 1)
                    
                    # Only notify zones with significant risk (e.g., risk >= 4 or safety <= 6)
                    if risk >= 4.0:
                        shelter = entry.get("assigned_shelter", "TBD")
                        route = entry.get("assigned_route", "Direct")
                        
                        # Find shelter name from ID if possible
                        shelter_name = shelter
                        for s in city_model.get("shelters", []):
                            if s["id"] == shelter:
                                shelter_name = s["name"]
                                break
                        
                        await send_twilio_notification(z_name, safety_score, shelter_name, route)
                        notifications_sent += 1
                
                logger.info(f"Sent emergency notifications to {notifications_sent} zones.")
    except WebSocketDisconnect:
        clients.discard(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
