import os
import json
import asyncio
import logging
from typing import Optional
from agents.safety_predictor import SafetyPredictor

logger = logging.getLogger("RiskForecastAgent")

class RiskForecastAgent:
    """
    Risk Forecast Agent:
    Outputs a flood risk score (0-10) for each zone.

    Hybrid mode:
      - Rule-based calculation (always runs, provides baseline scores)
      - LLM-enhanced analysis (when Ollama is available, provides reasoning)
    """
    def __init__(self, data_dir=None, ollama_client=None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.data_dir = data_dir
        self.scenarios = {}
        self._ollama = ollama_client
        self._last_llm_analysis: dict = {}  # zone_name -> {reasoning, risk_level, ...}
        
        # Phase 4: Stateful risk components
        self._soil_saturation = {}  # zone_name -> saturation_percentage (0-100)
        self._risk_history = {}     # zone_name -> [last N scores] for time_to_critical
        self._last_structured_output = {}  # zone_name -> full structured output
        self._last_tick = 0
        
        # Phase 6: AI Safety Prediction (Hugging Face)
        self._ai_predictor = SafetyPredictor()

        self._load_scenarios()

    def set_ollama_client(self, client) -> None:
        """Set or update the Ollama client (called after async init)."""
        self._ollama = client

    def _load_scenarios(self):
        for sf in ["moderate_flood", "severe_flood"]:
            path = os.path.join(self.data_dir, f"{sf}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.scenarios[sf] = data.get("ticks", [])

    def compute_base_risk(self, rainfall_mm_hr: float, water_level_m: float, elevation_tier: str, zone_name: str) -> float:
        """
        🌊 PHASE 4: Core Risk Computation
        
        Inputs:
            - rainfall_mm_hr: Intensity of precipitation
            - water_level_m: Current water level from sensors
            - elevation_tier: 'high', 'mid', 'low'
            - zone_name: For stateful saturation tracking
            
        Returns:
            - float: Risk score (0.0 - 10.0)
        """
        # 1. Calculate soil saturation (increases with rain, drains slowly)
        current_sat = self._soil_saturation.get(zone_name, 10.0) # Start at 10% base
        saturation_increase = (rainfall_mm_hr * 0.5) # Arbitrary scaling
        current_sat = min(100.0, current_sat + saturation_increase)
        
        # Slow drainage if no rain
        if rainfall_mm_hr < 1.0:
            current_sat = max(5.0, current_sat - 2.0)
            
        self._soil_saturation[zone_name] = current_sat

        # 2. Base Risk components
        # Rainfall contributes up to 4.0 points (at 80mm/hr)
        rain_component = (rainfall_mm_hr / 20.0) 
        
        # Water level contributes up to 6.0 points (at 3.0m)
        water_component = (water_level_m * 2.0)
        
        # Saturation contributes up to 2.0 points
        sat_component = (current_sat / 50.0)

        base_risk = rain_component + water_component + sat_component

        # 3. Elevation Modifiers
        modifiers = {
            "high": 0.6,   # Reduced risk
            "mid": 1.0,    # Normal
            "low": 1.5     # Significantly increased risk (basins)
        }
        modifier = modifiers.get(elevation_tier, 1.0)
        
        final_score = base_risk * modifier
        
        return round(max(0.0, min(10.0, final_score)), 2)

    # ── Phase 4: Time-to-Critical ─────────────────────────────────────────────
    def _compute_time_to_critical(self, zone_name: str, current_score: float) -> int:
        """Estimate ticks until risk reaches 10.0 based on rate of increase."""
        history = self._risk_history.get(zone_name, [])
        if len(history) < 2 or current_score >= 10.0:
            return 0 if current_score >= 10.0 else 99

        # Rate = average increase over last few ticks
        deltas = [history[i] - history[i - 1] for i in range(1, len(history))]
        avg_rate = sum(deltas) / len(deltas)

        if avg_rate <= 0.01:
            return 99  # stable or decreasing — no critical trajectory
        remaining = 10.0 - current_score
        return max(1, round(remaining / avg_rate))

    # ── Phase 4: Confidence Score ─────────────────────────────────────────────
    @staticmethod
    def _compute_confidence(rainfall: float, water_level: float, source: str = "rule-based") -> float:
        """
        Confidence in the risk score.
        Rule-based: 0.7–0.9 depending on input variance.
        """
        if source == "llm":
            return 0.85
        # Higher confidence when inputs are extreme (clearer signal)
        signal_strength = min((rainfall / 50.0 + water_level / 2.0) / 2.0, 1.0)
        return round(0.70 + signal_strength * 0.20, 2)

    # ── Phase 4: Scenario Tuning ──────────────────────────────────────────────
    _SCENARIO_MULTIPLIERS = {
        "moderate_flood": 1.0,   # baseline — slow increase
        "severe_flood": 1.5,     # extreme escalation — very high scores
    }

    def _calculate_flood_score(self, zone_data: dict, elevation_tier: str, zone_name: str,
                                scenario_type: str = "moderate_flood") -> float:
        """Compute flood score with scenario-aware tuning."""
        rainfall = zone_data.get("rainfall_mm", 0)
        water_level = zone_data.get("water_level_m", 0)
        base = self.compute_base_risk(rainfall, water_level, elevation_tier, zone_name)
        multiplier = self._SCENARIO_MULTIPLIERS.get(scenario_type, 1.0)
        return round(max(0.0, min(10.0, base * multiplier)), 2)

    # ── Phase 4: Structured Output ────────────────────────────────────────────
    def get_risk_scores(self, tick: int, scenario_type: str, city_model_zones: list) -> dict:
        """
        Returns a dict mapping zone_name -> risk_score (float 0.0 - 10.0).
        Also populates self._last_structured_output for detailed access.
        """
        scenario_data = self.scenarios.get(scenario_type)
        if not scenario_data:
            return {}

        actual_tick = ((tick - 1) % len(scenario_data)) + 1
        tick_data = next((t for t in scenario_data if t["tick"] == actual_tick), None)
        if not tick_data:
            return {}

        self._last_tick = tick
        scores = {}
        structured = {}

        for zone in city_model_zones:
            name = zone["name"]
            zd = tick_data["zones"].get(name, {})
            elev = zone.get("elevation_tier", "mid")
            rainfall = zd.get("rainfall_mm", 0)
            water_level = zd.get("water_level_m", 0)

            if "flood" in scenario_type:
                score = self._calculate_flood_score(zd, elev, name, scenario_type)
            else:
                score = zone.get("flood_risk_base", 0.0)

            # Track history for time_to_critical
            self._risk_history.setdefault(name, [])
            self._risk_history[name].append(score)
            if len(self._risk_history[name]) > 5:
                self._risk_history[name] = self._risk_history[name][-5:]

            ttc = self._compute_time_to_critical(name, score)
            confidence = self._compute_confidence(rainfall, water_level)

            scores[name] = score
            
            # AI-driven Safety Score (Hugging Face)
            ai_safety = self._ai_predictor.predict_safety_score(
                name, rainfall, water_level, elev, zone.get("population", 0)
            )

            structured[name] = {
                "risk_score": score,
                "safety_score_ai": ai_safety,
                "risk_level": self._risk_level_label(score),
                "time_to_critical": ttc,
                "confidence": confidence,
                "elevation_tier": elev,
                "rainfall_mm": rainfall,
                "water_level_m": water_level,
                "soil_saturation": round(self._soil_saturation.get(name, 0), 1),
                "scenario": scenario_type,
            }

        self._last_structured_output = structured
        return scores

    def get_structured_output(self) -> dict:
        """Return the last tick's full structured risk output (schema-compliant)."""
        return self._last_structured_output

    async def get_llm_risk_analysis(
        self,
        tick: int,
        scenario_type: str,
        city_model_zones: list,
        risk_scores: dict,
    ) -> dict:
        """
        Get LLM-enhanced risk analysis for all zones.

        Returns a dict mapping zone_name -> {
            "risk_score": float,
            "risk_level": str,
            "reasoning": str,
            "recommendations": str
        }

        Falls back to rule-based labels if Ollama is unavailable.
        """
        if self._ollama is None or not await self._ollama.is_available():
            # Fallback: generate simple rule-based analysis
            return self._generate_fallback_analysis(risk_scores)

        # Get the raw scenario data for context
        scenario_data = self.scenarios.get(scenario_type)
        if not scenario_data:
            return self._generate_fallback_analysis(risk_scores)

        actual_tick = ((tick - 1) % len(scenario_data)) + 1
        tick_data = next((t for t in scenario_data if t["tick"] == actual_tick), None)

        if not tick_data:
            return self._generate_fallback_analysis(risk_scores)

        # Build a compact data summary for the LLM
        zone_summaries = []
        for zone in city_model_zones:
            name = zone["name"]
            zd = tick_data["zones"].get(name, {})
            score = risk_scores.get(name, 0.0)
            summary = {
                "zone": name,
                "risk_score": score,
                "elevation": zone.get("elevation_tier", "mid"),
                "population": zone.get("population", 0),
                "elderly_pct": zone.get("elderly_pct", 0),
            }
            if "flood" in scenario_type:
                summary["rainfall_mm"] = zd.get("rainfall_mm", 0)
                summary["water_level_m"] = zd.get("water_level_m", 0)
            zone_summaries.append(summary)

        # Sort by risk_score descending so LLM focuses on high-risk zones
        zone_summaries.sort(key=lambda z: z["risk_score"], reverse=True)

        scenario_label = scenario_type.replace("_", " ").title()
        system_prompt = (
            "You are an expert disaster risk analyst for Bangalore, India. "
            "You analyze real-time sensor data from urban zones and provide "
            "concise risk assessments for emergency evacuation planning. "
            "Be specific and actionable. Use the data provided."
        )

        prompt = (
            f"SCENARIO: {scenario_label} | TICK: {tick}\n\n"
            f"Zone sensor data:\n{json.dumps(zone_summaries, indent=1)}\n\n"
            "For the TOP 5 highest-risk zones, provide a brief risk analysis. "
            "Respond ONLY with a valid JSON object in this exact format:\n"
            "{\n"
            '  "zone_name_1": {"risk_level": "critical|high|moderate|low", '
            '"reasoning": "1-2 sentences explaining why", '
            '"recommendation": "1 sentence action"},\n'
            '  "zone_name_2": {...}\n'
            "}\n"
            "Use actual zone names from the data. No markdown, no extra text."
        )

        try:
            result = await self._ollama.generate_json(
                prompt=prompt,
                system=system_prompt,
                temperature=0.3,
                max_tokens=800,
            )

            if result and isinstance(result, dict):
                # Merge LLM analysis with rule-based scores
                analysis = {}
                for zone_name, score in risk_scores.items():
                    llm_data = result.get(zone_name, {})
                    analysis[zone_name] = {
                        "risk_score": score,
                        "risk_level": llm_data.get("risk_level", self._risk_level_label(score)),
                        "reasoning": llm_data.get("reasoning", self._default_reasoning(zone_name, score, scenario_type)),
                        "recommendation": llm_data.get("recommendation", "Monitor situation."),
                        "source": "llm" if zone_name in result else "rule-based",
                    }
                self._last_llm_analysis = analysis
                return analysis
        except Exception as e:
            logger.warning(f"LLM risk analysis failed: {e}")

        return self._generate_fallback_analysis(risk_scores)

    def get_last_llm_analysis(self) -> dict:
        """Return the most recent LLM analysis (cached between ticks)."""
        return self._last_llm_analysis

    def _generate_fallback_analysis(self, risk_scores: dict) -> dict:
        """Generate rule-based analysis when LLM is unavailable."""
        analysis = {}
        for zone_name, score in risk_scores.items():
            analysis[zone_name] = {
                "risk_score": score,
                "risk_level": self._risk_level_label(score),
                "reasoning": self._default_reasoning(zone_name, score, "general"),
                "recommendation": self._default_recommendation(score),
                "source": "rule-based",
            }
        return analysis

    @staticmethod
    def _risk_level_label(score: float) -> str:
        if score >= 9.0:
            return "critical"
        elif score >= 7.0:
            return "high"
        elif score >= 4.0:
            return "moderate"
        elif score >= 2.0:
            return "low"
        return "minimal"

    @staticmethod
    def _default_reasoning(zone_name: str, score: float, scenario: str) -> str:
        level = RiskForecastAgent._risk_level_label(score)
        return f"{zone_name} shows {level} risk (score: {score:.1f}/10) based on current {scenario} conditions."

    @staticmethod
    def _default_recommendation(score: float) -> str:
        if score >= 9.0:
            return "Immediate evacuation required."
        elif score >= 7.0:
            return "Prepare for potential evacuation."
        elif score >= 4.0:
            return "Heightened monitoring advised."
        return "Continue routine monitoring."
