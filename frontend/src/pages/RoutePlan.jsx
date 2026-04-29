// ... imports remain the same
import React, { useState, useEffect } from 'react';
import cityData from '../data/city-model.json';
import { useGlobalSocket } from '../context/SocketContext';
import { MapContainer, TileLayer, Marker, Polyline, Popup } from 'react-leaflet';
import L from 'leaflet';

// Real Bengaluru Latitude/Longitude approximations
const GEO_COORDS = {
  Z01: [12.9698, 77.7499], // Whitefield
  Z02: [12.9279, 77.6271], // Koramangala
  Z03: [12.9121, 77.6446], // HSR Layout
  Z04: [12.8601, 77.7850], // Sarjapur
  Z05: [12.9716, 77.6411], // Indiranagar
  Z06: [12.9880, 77.6690], // Mahadevapura
  Z07: [12.9304, 77.6784], // Bellandur
  Z08: [12.9569, 77.7011], // Marathahalli
  Z09: [12.9166, 77.6101], // BTM Layout
  Z10: [12.8399, 77.6770], // Electronic City
  Z11: [13.0354, 77.5988], // Hebbal
  Z12: [13.1007, 77.5963], // Yelahanka
  Whitefield: [12.9698, 77.7499],
  Koramangala: [12.9279, 77.6271],
  'HSR Layout': [12.9121, 77.6446],
  Sarjapur: [12.8601, 77.7850],
  Indiranagar: [12.9716, 77.6411],
  Mahadevapura: [12.9880, 77.6690],
  Bellandur: [12.9304, 77.6784],
  Marathahalli: [12.9569, 77.7011],
  'BTM Layout': [12.9166, 77.6101],
  'Electronic City': [12.8399, 77.6770],
  Hebbal: [13.0354, 77.5988],
  Yelahanka: [13.1007, 77.5963]
};

const SHELTER_COORDS = {
  S01: [13.035, 77.590], // Hebbal Shelter (RMC Ground Approx)
  S02: [13.100, 77.600], // Yelahanka Shelter (Kanteerava Approx)
  S03: [12.972, 77.755], // Whitefield Shelter (ITPL Approx)
};

const getLatLng = (id) => GEO_COORDS[id] || SHELTER_COORDS[id];

const getZoneIcon = (risk) => {
  let color = '#aaffdc'; // Stable (Emerald)
  let shadow = '#aaffdc';
  
  if (risk >= 9) {
    color = '#ef4444'; // Red
    shadow = '#ef4444';
  } else if (risk >= 7) {
    color = '#f97316'; // Orange
    shadow = '#f97316';
  } else if (risk >= 5) {
    color = '#eab308'; // Yellow
    shadow = '#eab308';
  }

  return L.divIcon({
    className: 'custom-icon',
    html: `<div style="width: 14px; height: 14px; background-color: ${color}; border-radius: 50%; border: 2px solid #000; box-shadow: 0 0 10px ${shadow}; transition: all 0.5s ease;"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7]
  });
};

const shelterIcon = L.divIcon({
  className: 'custom-icon',
  html: `<div style="width: 16px; height: 16px; background-color: #ffffff; border-radius: 2px; border: 2px solid #aaffdc; box-shadow: 0 0 12px #ffffff;"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8]
});

const EvacuationUnit = ({ path, delay = 0 }) => {
  const [pos, setPos] = useState(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!path || path.length < 2) return;

    let interval;
    const startTimeout = setTimeout(() => {
      interval = setInterval(() => {
        setIndex(prev => {
          if (prev >= path.length - 1) return 0;
          return prev + 1;
        });
      }, 150); // Speed up slightly for dots
    }, delay);

    return () => {
      clearTimeout(startTimeout);
      if (interval) clearInterval(interval);
    };
  }, [path.length, delay]);

  useEffect(() => {
    if (path && path[index]) {
      setPos(path[index]);
    }
  }, [index, path]);

  if (!pos) return null;

  return (
    <Marker
      position={pos}
      icon={L.divIcon({
        className: 'evacuation-dot',
        html: `<div style="width: 8px; height: 8px; background-color: #2563eb; border-radius: 50%; box-shadow: 0 0 12px #2563eb, 0 0 4px #fff; border: 1px solid rgba(255,255,255,0.3);"></div>`,
        iconSize: [8, 8],
        iconAnchor: [4, 4]
      })}
      interactive={false}
    />
  );
};

export default function RoutePlan() {
  const { data, isConnected } = useGlobalSocket();
  const [tick, setTick] = useState(0);
  const [activeRoutes, setActiveRoutes] = useState([]);
  const [map, setMap] = useState(null);

  const [osrmCache, setOsrmCache] = useState({});

  const edges = cityData.road_network.edges;

  // Stable calculation of OSRM paths to prevent animation jitter
  const renderOsrmPath = React.useCallback((pointArray) => {
    let fullPath = [];
    for (let i = 0; i < pointArray.length - 1; i++) {
      const p1 = getLatLng(pointArray[i]);
      const p2 = getLatLng(pointArray[i + 1]);
      if (!p1 || !p2) continue;

      const key = `${p1[1]},${p1[0]};${p2[1]},${p2[0]}`;
      if (osrmCache[key]) {
        fullPath = fullPath.concat(osrmCache[key]);
      } else {
        fullPath.push(p1);
        fullPath.push(p2);
      }
    }
    return fullPath;
  }, [osrmCache]);

  const memoizedPaths = React.useMemo(() => {
    return activeRoutes.map(route => ({
      ...route,
      geoPath: renderOsrmPath(route.path)
    }));
  }, [activeRoutes, renderOsrmPath]);

  const memoizedEdges = React.useMemo(() => {
    return edges.map(edge => renderOsrmPath(edge));
  }, [edges, renderOsrmPath]);

  useEffect(() => {
    // Remove the hacky CSS filter
    document.documentElement.style.removeProperty('--leaflet-tile-filter');
  }, []);

  // Force Leaflet to recalculate size when component mounts fully
  useEffect(() => {
    if (map) {
      setTimeout(() => {
        map.invalidateSize();
      }, 500);
    }
  }, [map]);

  useEffect(() => {
    if (data && data.tick !== undefined) {
      setTick(data.tick);
      if (data.routes && data.evacuation_plan) {
        const sortedZones = [...data.evacuation_plan.evacuation_sequence]
          .filter(item => data.routes[item.zone_name])
          .sort((a, b) => {
            const aRisk = a.risk_score ?? 0;
            const bRisk = b.risk_score ?? 0;
            if (bRisk !== aRisk) return bRisk - aRisk;
            return (b.priority_score ?? 0) - (a.priority_score ?? 0);
          });

        const top3 = sortedZones.slice(0, 3);
        const routesArray = top3.map((item, index) => {
          const route = data.routes[item.zone_name];
          const liveZone = data.city_model?.zones?.find(z => z.id === item.zone_id || z.name === item.zone_name);
          return {
            from: item.zone_name,
            to: route.to_zone,
            path: route.path,
            humans: item.next_batch_size || liveZone?.population || 0,
            status: route.status,
            rank: index + 1,
            risk_score: item.risk_score ?? 0,
          };
        });
        setActiveRoutes(routesArray);
      }
    }
  }, [data]);



  // Background Async Fetcher for OSRM GeoJSON Paths
  useEffect(() => {
    const fetchPath = async (p1, p2) => {
      const key = `${p1[1]},${p1[0]};${p2[1]},${p2[0]}`; // OSRM is Lng,Lat
      if (osrmCache[key]) return; // Already fetched
      try {
        const res = await fetch(`https://router.project-osrm.org/route/v1/driving/${key}?geometries=geojson`);
        if (!res.ok) return;
        const json = await res.json();
        if (json.code === 'Ok' && json.routes.length > 0) {
          // Convert GeoJSON (Lng, Lat) to Leaflet (Lat, Lng)
          const mapped = json.routes[0].geometry.coordinates.map(coord => [coord[1], coord[0]]);
          setOsrmCache(prev => ({ ...prev, [key]: mapped }));
        }
      } catch (e) {
        console.error("OSRM Route Error: ", e);
      }
    };

    const pairsToFetch = [];
    edges.forEach(edge => {
      const start = getLatLng(edge[0]);
      const end = getLatLng(edge[1]);
      if (start && end) pairsToFetch.push([start, end]);
    });

    activeRoutes.forEach(r => {
      for (let i = 0; i < r.path.length - 1; i++) {
        const start = getLatLng(r.path[i]);
        const end = getLatLng(r.path[i + 1]);
        if (start && end) pairsToFetch.push([start, end]);
      }
    });

    const uniquePairs = [];
    const seen = new Set();
    pairsToFetch.forEach(pair => {
      const key = `${pair[0][0]},${pair[0][1]}_${pair[1][0]},${pair[1][1]}`;
      if (!seen.has(key)) {
        seen.add(key);
        uniquePairs.push(pair);
      }
    });

    const loadAll = async () => {
      for (let i = 0; i < uniquePairs.length; i++) {
        await new Promise(resolve => setTimeout(resolve, 300)); // Safer OSRM rate limit
        await fetchPath(uniquePairs[i][0], uniquePairs[i][1]);
      }
    };

    loadAll();
  }, [edges, activeRoutes]); // Re-run if routes change

  return (
    <div className="flex flex-col h-full space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-800 pb-2">
        <div className="flex items-center gap-4">
          <span className="text-xs font-bold text-primary tracking-[0.2em] uppercase">
            Route Plan Simulation
          </span>
          <div className="h-4 w-px bg-gray-800"></div>
          <span className="text-[10px] font-mono text-gray-500 uppercase tracking-widest">
            Mobility_Agent_V.1.2 // Live_Tick: {tick}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
            <span className="text-[10px] text-gray-400 uppercase font-bold">Mobilization Alpha</span>
          </div>
          <div className="text-[10px] font-mono text-gray-500 tracking-widest uppercase">
            CartoDB geo overlays
          </div>
        </div>
      </div>

      <div className="flex flex-1 relative overflow-hidden rounded-lg border border-white/10 shadow-[0_0_50px_rgba(0,0,0,0.5)]">
        {/* Real Map Area - Full Screen Mode ("Only One") */}
        <div className="absolute inset-0 z-0">
          <style>
            {`
              .leaflet-container {
                background: #0b0b0d;
                font-family: inherit;
              }
              .custom-popup .leaflet-popup-content-wrapper {
                background: rgba(15, 15, 20, 0.9);
                backdrop-filter: blur(8px);
                color: #fff;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
              }
              .custom-popup .leaflet-popup-tip {
                background: rgba(15, 15, 20, 0.9);
              }
              @keyframes dash {
                to {
                  stroke-dashoffset: -20;
                }
              }
              .best-path-glow {
                filter: drop-shadow(0 0 8px #aaffdc);
                animation: dash 1s linear infinite;
              }
              .moving-chevron {
                pointer-events: none;
                z-index: 1000;
              }
            `}
          </style>

          <MapContainer
            ref={setMap}
            center={[12.9716, 77.6411]}
            zoom={12}
            scrollWheelZoom={true}
            style={{ height: '100%', width: '100%' }}
            zoomControl={false}>

            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />

            {/* Render Static Network Edges */}
            {memoizedEdges.map((pathGeo, i) => {
              if (!pathGeo || pathGeo.length < 2) return null;
              return (
                <Polyline
                  key={`edge-${i}`}
                  positions={pathGeo}
                  color="#2a454d"
                  weight={1.5}
                  opacity={0.4}
                  dashArray="5 5"
                />
              );
            })}

            {/* Render Active Replanned Routes */}
            {memoizedPaths.map((route, i) => {
              const pathGeo = route.geoPath;
              if (!pathGeo || pathGeo.length < 2) return null;

              // Check if this is the "Best" (Top Priority) Path
              const isTopRoute = i === 0;

              return (
                <React.Fragment key={`route-group-${i}`}>
                  {/* Secondary glow layer for top route */}
                  {isTopRoute && (
                    <Polyline
                      positions={pathGeo}
                      color="#aaffdc"
                      weight={8}
                      opacity={0.3}
                    />
                  )}

                  <Polyline
                    positions={pathGeo}
                    color={route.status === 'ok' ? '#aaffdc' : '#ff716c'}
                    weight={route.rank === 1 ? 5 : route.rank === 2 ? 4 : 3}
                    opacity={route.rank === 1 ? 0.95 : route.rank === 2 ? 0.75 : 0.55}
                    dashArray={route.rank === 1 ? "10, 10" : "none"}
                    className={route.rank === 1 ? "best-path-glow" : ""}
                  >
                    <Popup className="custom-popup">
                      <div className="p-1">
                        <div className="text-[10px] font-black text-primary uppercase">PRIORITY {route.rank} PATH</div>
                        <div className="text-[8px] text-white/60 font-mono">ZONE: {route.from}</div>
                        <div className="text-[8px] text-white/60 font-mono">RISK: {route.risk_score?.toFixed(1)}</div>
                        <div className="text-[8px] text-white/60 font-mono">FLOW: {route.humans} HUMAN_UNITS</div>
                      </div>
                    </Popup>
                  </Polyline>

                  {/* Animated Moving Dots along the highest-priority path */}
                  {route.rank === 1 && (
                    <>
                      <EvacuationUnit path={pathGeo} delay={0} />
                      <EvacuationUnit path={pathGeo} delay={1500} />
                      <EvacuationUnit path={pathGeo} delay={3000} />
                    </>
                  )}
                </React.Fragment>
              );
            })}

            {Object.entries(GEO_COORDS).filter(([k]) => k.startsWith('Z')).map(([id, coord]) => {
              const liveZone = data?.city_model?.zones?.find(z => z.id === id);
              const zoneName = liveZone?.name || id;
              const isEvacuated = liveZone?.status === 'evacuated';
              const risk = liveZone?.risk_score ?? liveZone?.flood_risk_base ?? 0;
              
              return (
                <Marker key={id} position={coord} icon={getZoneIcon(risk)} opacity={isEvacuated ? 0.3 : 1}>
                  <Popup className="custom-popup">
                    <div className="p-1">
                      <div className="text-[10px] font-black text-primary tracking-widest uppercase mb-1">
                        {zoneName} {isEvacuated && "(EVACUATED)"}
                      </div>
                      <div className="text-[8px] text-gray-400 font-mono">
                        REMAINING POP: {liveZone?.remaining_population?.toLocaleString() ?? liveZone?.population?.toLocaleString() ?? "N/A"}
                      </div>
                      <div className="text-[8px] text-gray-400 font-mono">RISK: {risk.toFixed(1)}</div>
                    </div>
                  </Popup>
                </Marker>
              )
            })}


            {/* Render Shelters (Markers) */}
            {cityData.shelters.map(shelter => {
              const coord = SHELTER_COORDS[shelter.id];
              if (!coord) return null;
              return (
                <Marker key={shelter.id} position={coord} icon={shelterIcon}>
                  <Popup className="custom-popup">
                    <div className="p-1">
                      <div className="text-[10px] font-black text-white tracking-widest uppercase mb-1">SHELTER: {shelter.name}</div>
                      <div className="text-[8px] text-emerald-400 font-mono">CAPACITY: {shelter.capacity}</div>
                    </div>
                  </Popup>
                </Marker>
              )
            })}

          </MapContainer>

          <div className="absolute bottom-6 left-6 flex flex-col gap-3 pointer-events-none z-[1000]">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-black text-black tracking-[0.4em] uppercase bg-primary px-2 py-0.5 shadow-lg w-fit">BENGALURU_METRO</span>
              <span className="text-[8px] font-mono text-primary bg-black/80 px-2 py-0.5 tracking-[0.2em] uppercase w-fit">Geo_Tactical_Overlay_Enabled</span>
            </div>

            <div className="bg-black/80 backdrop-blur-md border border-white/10 p-2.5 rounded flex flex-col gap-2 pointer-events-auto">
               <span className="text-[8px] font-black text-gray-500 uppercase tracking-widest border-b border-white/5 pb-1 mb-0.5">Risk Legend</span>
               <div className="flex gap-4">
                  {[
                    { label: 'Critical', color: 'bg-[#ef4444]' },
                    { label: 'High', color: 'bg-[#f97316]' },
                    { label: 'Elevated', color: 'bg-[#eab308]' },
                    { label: 'Stable', color: 'bg-[#aaffdc]' }
                  ].map(item => (
                    <div key={item.label} className="flex items-center gap-1.5">
                      <div className={`w-2 h-2 rounded-full ${item.color} shadow-[0_0_5px_currentColor]`}></div>
                      <span className="text-[7px] text-gray-400 uppercase font-bold tracking-tighter">{item.label}</span>
                    </div>
                  ))}
               </div>
            </div>
          </div>
        </div>

        {/* Info Panel Overlay - Floating Premium Glassmorphism */}
        <div className="absolute top-6 right-6 w-80 z-[1000] max-h-[calc(100%-3rem)] flex flex-col pointer-events-none">
          <div className="bg-black/60 backdrop-blur-xl border border-white/10 p-4 space-y-4 flex flex-col shadow-2xl pointer-events-auto rounded-lg overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 pb-2">
              <h3 className="text-[10px] font-black text-primary tracking-[0.2em] uppercase">Tactical_Relocation_Feed</h3>
              <span className="text-[8px] font-mono text-emerald-500 animate-pulse">● SIGNAL_OK</span>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto no-scrollbar max-h-80">
              {activeRoutes.length > 0 ? activeRoutes.map((route, i) => (
                <div key={i} className="group relative p-3 bg-white/5 border border-white/5 hover:border-primary/40 transition-all rounded-sm">
                  <div className="absolute top-0 left-0 w-0.5 h-full bg-primary/20 group-hover:bg-primary transition-all"></div>
                  <div className="flex justify-between items-start mb-2">
                    <div className="flex flex-col">
                      <span className="text-[7px] text-gray-500 uppercase font-black tracking-widest">Vector</span>
                      <span className="text-[10px] font-bold text-gray-100">{route.from} ➔ {route.to.slice(0, 3)}</span>
                    </div>
                    <div className="flex flex-col items-end">
                      <span className="text-[7px] text-gray-500 uppercase font-black tracking-widest">Status</span>
                      <span className={`text-[9px] font-black ${route.status === 'ok' ? 'text-emerald-400' : 'text-orange-400'}`}>
                        {route.status.toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-end justify-between">
                    <div className="text-lg font-mono font-black text-white leading-none">
                      {route.humans} <span className="text-[8px] text-gray-500 font-normal">SOULS</span>
                    </div>
                    <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
                      <div className="h-full bg-primary" style={{ width: '70%' }}></div>
                    </div>
                  </div>
                </div>
              )) : (
                <div className="text-[9px] text-gray-500 italic font-mono py-4 text-center">INITIALIZING_VECTORS...</div>
              )}
            </div>

            <div className="pt-4 border-t border-white/10 space-y-3">
              <div className="flex justify-between items-center text-[8px] text-white/40 font-black uppercase tracking-[0.2em]">
                <span>Node_Sync_Lat</span>
                <span className="text-primary">12.4ms</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                <div className="bg-white/5 p-2 rounded-sm border border-white/5 flex flex-col">
                  <span className="text-gray-500 text-[7px] font-bold">REPLAN</span>
                  <span className="text-white text-[9px]">AUTOMATIC</span>
                </div>
                <div className="bg-white/5 p-2 rounded-sm border border-white/5 flex flex-col">
                  <span className="text-gray-500 text-[7px] font-bold">MODE</span>
                  <span className="text-emerald-400 text-[9px]">TACTICAL</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

