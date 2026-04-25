# ADEO — Autonomous Disaster Evacuation Orchestrator

**ADEO** is a high-fidelity, full-stack simulation platform for managing and visualizing urban disaster evacuations in real-time. Optimized for the **Bengaluru road network**, it combines AI-driven multi-agent decision-making with premium geospatial visualizations.

---

## 🚀 Key Features

### 🗺️ Immersive Tactical Dashboard
- **Full-Screen Bangalore Map** — Leaflet-based map with CartoDB dark-mode topography.
- **Kinetic Flow Indicators** — Animated directional chevrons (`>>>`) that track along actual OSRM street paths to show real-time evacuation movement.
- **Optimal Route Highlighting** — Dynamic glowing paths for the highest-priority evacuation vectors.
- **Glassmorphic Tactical Overlays** — Futuristic UI panels for live status feeds, simulation ticks, and unit-flow monitoring.

### 🧠 Multi-Agent Intelligence
| Agent | Responsibility |
|---|---|
| **Mobility Agent** | Manages the road network graph (17 nodes, 24 arterial edges), calculates curved OSRM street paths, and bridges data over WebSocket. |
| **Risk Agent** | Evaluates real-time risk scores per evacuation zone. |
| **Vulnerability Agent** | Assesses population vulnerability factors (elderly ratio, infrastructure fragility). |
| **Decision Governor** | Ranks evacuation zones using weighted scoring (risk, vulnerability, road capacity) and computes optimal shelter assignments. |

### ⚡ Adaptive Re-planning
- Automatically reroutes evacuations in real-time if a road becomes flooded or blocked.
- Configurable cooldown (`replan_cooldown_ticks`) and risk threshold (`risk_threshold_for_replan`) via `config.json`.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Frontend** | React 18, Vite 5, Tailwind CSS 3, Leaflet, React-Leaflet, React Router v7 |
| **Backend** | FastAPI, Uvicorn (WebSocket), NetworkX |
| **AI / ML** | scikit-learn, NumPy, SciPy, Pandas |
| **Geographic Data** | OpenStreetMap `.osm.pbf`, OSRM API for street-level routing |

---

## 📦 Getting Started

### Prerequisites
- **Python** 3.9+
- **Node.js** 16+ (with npm)

### 1. Clone the Repository
```bash
git clone <repo-url>
cd ADEO_UIP17
```

### 2. Backend Setup
```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# Install Python dependencies
pip install -r requirements.txt

# Start the API server
uvicorn backend.main:app --reload
```
The API will be available at **`http://localhost:8000`**.

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The dashboard will be available at **`http://localhost:5173/route-plan`**.

---

## 📂 Project Structure

```text
ADEO_UIP17/
│
├── backend/
│   └── main.py                      # FastAPI app, WebSocket endpoint, simulation loop
│
├── agents/
│   ├── mobility_agent/
│   │   ├── mobility_agent.py        # Road-network graph & OSRM path computation
│   │   ├── road_extraction.py       # OSM road data extraction
│   │   ├── road_selection.py        # Arterial road selection logic
│   │   ├── simulation_integration.py# Tick-based simulation bridge
│   │   └── websocket_bridge.py      # Real-time WebSocket data bridge
│   ├── vulnerability_agent/
│   │   └── vulnerability_agent.py   # Population vulnerability scoring
│   ├── risk_agent.py                # Zone risk evaluation
│   └── decision_governor.py         # High-level agent coordination
│
├── decision_governor/
│   ├── decision_governor.py         # Weighted priority ranking & shelter assignment
│   ├── rationale_generator.py       # Human-readable decision rationale
│   ├── summary_generator.py         # Evacuation summary reports
│   └── city_model_schema.json       # City model JSON schema definition
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── RoutePlan.jsx        # Primary tactical map controller
│   │   │   ├── Orchestration.jsx    # Multi-agent orchestration view
│   │   │   ├── ZonalAnalysis.jsx    # Zone-level analysis dashboard
│   │   │   ├── ShelterStatus.jsx    # Shelter capacity & status monitor
│   │   │   └── ReplanLog.jsx        # Re-planning event log
│   │   ├── components/
│   │   │   ├── Navbar.jsx           # Top navigation bar
│   │   │   └── Sidebar.jsx          # Side navigation panel
│   │   ├── context/                 # React context providers
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── data/                    # Static data / mock fixtures
│   │   ├── App.jsx                  # Root component & routing
│   │   ├── main.jsx                 # Application entry point
│   │   └── index.css                # Global styles
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.js
│   └── index.html
│
├── schemas/
│   └── agent_contracts.json         # Inter-agent communication contracts
│
├── config.json                      # Decision Governor tunables
├── requirements.txt                 # Python dependencies
├── test_decision_governor.py        # Decision Governor unit tests
├── test_mobility_agent.py           # Mobility Agent unit tests
└── .gitignore
```

---

## 📡 API & WebSocket Integration

The frontend connects to the backend via **WebSocket** at `ws://localhost:8000/ws` to receive real-time simulation updates:

| Message Key | Description |
|---|---|
| `tick` | Current time step of the disaster simulation |
| `routes` | Active evacuation paths, status, and flow data |
| `evacuation_plan` | Ordered list of priority zones with shelter assignments |

---

## ⚙️ Configuration

All Decision Governor tunables are in **`config.json`**:

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

---

## 🧪 Testing

```bash
# Run Decision Governor tests
python -m pytest test_decision_governor.py -v

# Run Mobility Agent tests
python -m pytest test_mobility_agent.py -v
```

---

## 🛡️ License

*Internal Project for ADEO UIP17 — All Rights Reserved.*
