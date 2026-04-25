"""
mobility_agent/road_selection.py
==================================
Section B — Road Selection

Defines the 5 key arterial roads of Bengaluru with:
- Capacity classification (high / medium / low)
- Passenger Car Unit (PCU) equivalents
- Flood risk thresholds
- OSM name variants for graph-matching
"""

from dataclasses import dataclass, field
from typing import Literal

CapacityLevel = Literal["high", "medium", "low"]

# Maximum vehicles per hour (PCU) per capacity tier
CAPACITY_PCU: dict[str, int] = {
    "high":   3600,   # 4-lane divided highway / national highway
    "medium": 1800,   # 2-lane arterial / major city road
    "low":    900,    # single-lane / narrow collector
}


@dataclass
class ArterialRoad:
    name: str
    capacity: CapacityLevel
    osm_name_variants: list[str]
    flood_risk_threshold: float   # [0.0 – 1.0] risk score to disable this road

    @property
    def capacity_pcu(self) -> int:
        return CAPACITY_PCU[self.capacity]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "capacity_pcu": self.capacity_pcu,
            "osm_name_variants": self.osm_name_variants,
            "flood_risk_threshold": self.flood_risk_threshold,
        }


# ── Bengaluru Key Arterial Roads ──────────────────────────────────────────────

ARTERIAL_ROADS: list[ArterialRoad] = [
    ArterialRoad(
        name="NH44",
        capacity="high",
        osm_name_variants=["NH 44", "NH44", "National Highway 44",
                           "Bellary Road", "NH-44"],
        flood_risk_threshold=0.75,
    ),
    ArterialRoad(
        name="Outer Ring Road",
        capacity="high",
        osm_name_variants=["Outer Ring Road", "ORR", "NICE Road",
                           "Outer Ring Rd"],
        flood_risk_threshold=0.70,
    ),
    ArterialRoad(
        name="Sarjapur Road",
        capacity="medium",
        osm_name_variants=["Sarjapur Road", "Sarjapur Main Road",
                           "Sarjapur - Marathahalli Road"],
        flood_risk_threshold=0.55,
    ),
    ArterialRoad(
        name="Hosur Road",
        capacity="medium",
        osm_name_variants=["Hosur Road", "Hosur Main Road",
                           "NH 648", "NH648"],
        flood_risk_threshold=0.60,
    ),
    ArterialRoad(
        name="Bellary Road",
        capacity="high",
        osm_name_variants=["Bellary Road", "NH 44", "Hebbal Flyover Road",
                           "Ballary Road"],
        flood_risk_threshold=0.75,
    ),
]

# Fast lookup by road name
ARTERIAL_ROAD_MAP: dict[str, ArterialRoad] = {r.name: r for r in ARTERIAL_ROADS}


def get_road_by_osm_name(osm_name: str) -> ArterialRoad | None:
    """Return the ArterialRoad that matches an OSM edge name, or None."""
    name_lower = osm_name.lower()
    for road in ARTERIAL_ROADS:
        for variant in road.osm_name_variants:
            if variant.lower() in name_lower or name_lower in variant.lower():
                return road
    return None


def get_capacity_pcu(capacity: CapacityLevel) -> int:
    return CAPACITY_PCU[capacity]


if __name__ == "__main__":
    print("Bengaluru Arterial Roads:")
    print("-" * 60)
    for road in ARTERIAL_ROADS:
        print(
            f"  {road.name:<22} "
            f"Capacity: {road.capacity:<8} "
            f"({road.capacity_pcu} PCU/hr)  "
            f"Flood threshold: {road.flood_risk_threshold}"
        )
