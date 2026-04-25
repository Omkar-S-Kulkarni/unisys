import os
import json

class RiskForecastAgent:
    """
    Risk Forecast Agent:
    Outputs a flood or heatwave risk score (0-10) for each zone
    based on rule-based logic reading from synthetic scenario data.
    """
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.data_dir = data_dir
        self.scenarios = {}
        
        self._load_scenarios()

    def _load_scenarios(self):
        for sf in ["moderate_flood", "severe_flood", "heatwave"]:
            path = os.path.join(self.data_dir, f"{sf}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.scenarios[sf] = data.get("ticks", [])

    def _calculate_flood_score(self, zone_data: dict, elevation_tier: str) -> float:
        rainfall = zone_data.get("rainfall_mm", 0)
        water_level = zone_data.get("water_level_m", 0)
        
        # Rule-based calculation
        score = (rainfall / 15.0) + (water_level * 1.5)
        
        # Elevation modifies the severity
        if elevation_tier == "high":
            score *= 0.6
        elif elevation_tier == "low":
            score *= 1.4
            
        return round(max(0.0, min(10.0, score)), 2)
        
    def _calculate_heatwave_score(self, zone_data: dict, elevation_tier: str) -> float:
        temp = zone_data.get("temperature_c", 0)
        hum = zone_data.get("humidity_pct", 0)
        
        # Rule-based heat index proxy
        score = ((temp - 30.0) * 0.8) + ((hum - 30.0) * 0.05)
        
        # Dense vs open areas (using elevation as a proxy for urban layout for synthetic purposes if needed,
        # but technically should use density. We'll stick to a simple formula for the demo).
        if elevation_tier == "high":
            score -= 0.5  # slight cooling effect
            
        return round(max(0.0, min(10.0, score)), 2)

    def get_risk_scores(self, tick: int, scenario_type: str, city_model_zones: list) -> dict:
        """
        Returns a dict mapping zone_name -> risk_score (float 0.0 - 10.0)
        """
        scenario_data = self.scenarios.get(scenario_type)
        if not scenario_data:
            return {}
            
        # Loop the ticks if simulation runs longer than the defined script
        actual_tick = ((tick - 1) % len(scenario_data)) + 1
        tick_data = next((t for t in scenario_data if t["tick"] == actual_tick), None)
        
        if not tick_data:
            return {}
            
        scores = {}
        for zone in city_model_zones:
            name = zone["name"]
            zd = tick_data["zones"].get(name, {})
            elev = zone.get("elevation_tier", "mid")
            
            if "flood" in scenario_type:
                scores[name] = self._calculate_flood_score(zd, elev)
            elif "heatwave" in scenario_type:
                scores[name] = self._calculate_heatwave_score(zd, elev)
            else:
                scores[name] = zone.get("flood_risk_base", 0.0)
                
        return scores
