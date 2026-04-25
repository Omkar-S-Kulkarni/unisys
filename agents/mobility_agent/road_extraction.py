"""
mobility_agent/road_extraction.py
==================================
Section A — Road Data Extraction

Downloads the Bengaluru drive network from OpenStreetMap using OSMnx,
and saves it as bengaluru_roads.graphml for use by the Mobility Agent.

Usage:
    python road_extraction.py
    python road_extraction.py --output /path/to/custom.graphml
"""

import argparse
import os
import sys

try:
    import osmnx as ox
except ImportError:
    print("[ERROR] osmnx not installed. Run: pip install osmnx")
    sys.exit(1)

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "bengaluru_roads.graphml"
)


def download_bengaluru_road_network(save_path: str = DEFAULT_OUTPUT) -> object:
    """
    Download Bengaluru's drivable road network from OSM and save as GraphML.

    Returns:
        MultiDiGraph: the downloaded OSMnx graph
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    print("[RoadExtraction] Querying OpenStreetMap for Bengaluru road network...")
    print("[RoadExtraction] This may take 1-3 minutes on first run...")

    G = ox.graph_from_place(
        "Bengaluru, Karnataka, India",
        network_type="drive",
        simplify=True,
    )

    # Add useful edge attributes for simulation
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    ox.save_graphml(G, filepath=save_path)

    print(f"[RoadExtraction] ✓ Saved to: {save_path}")
    print(f"[RoadExtraction]   Nodes : {len(G.nodes):,}")
    print(f"[RoadExtraction]   Edges : {len(G.edges):,}")

    return G


def load_road_network(path: str = DEFAULT_OUTPUT) -> object:
    """Load a previously saved GraphML file."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"GraphML not found at {path}. "
            "Run download_bengaluru_road_network() first."
        )
    print(f"[RoadExtraction] Loading road network from {path}...")
    G = ox.load_graphml(path)
    print(f"[RoadExtraction] ✓ Loaded — Nodes: {len(G.nodes):,}, Edges: {len(G.edges):,}")
    return G


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Bengaluru road network")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help="Output path for the .graphml file"
    )
    args = parser.parse_args()
    download_bengaluru_road_network(args.output)
