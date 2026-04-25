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
  Yelahanka: [13.1007, 77.5963],
  Jayanagar: [12.9250, 77.5938],
  Rajajinagar: [12.9982, 77.5530]
};

const SHELTER_COORDS = {
  S01: [12.972, 77.755], // Whitefield Shelter (Approx)
  S02: [13.035, 77.590], // Hebbal Shelter (Approx)
  S03: [13.100, 77.600], // Yelahanka Shelter (Approx)
};

const getLatLng = (id) => GEO_COORDS[id] || SHELTER_COORDS[id];

const zoneIcon = L.divIcon({
  className: 'custom-icon',
  html: `<div style="width: 12px; height: 12px; background-color: #aaffdc; border-radius: 50%; border: 2px solid #000; box-shadow: 0 0 8px #aaffdc;"></div>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6]
});

const shelterIcon = L.divIcon({
  className: 'custom-icon',
  html: `<div style="width: 14px; height: 14px; background-color: #ffffff; border-radius: 2px; border: 2px solid #aaffdc; box-shadow: 0 0 10px #ffffff;"></div>`,
  iconSize: [14, 14],
  iconAnchor: [7, 7]
});

const MovingChevron = ({ path, delay = 0 }) => {
  const [pos, setPos] = useState(null);
  const [angle, setAngle] = useState(0);
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
          }, 300); // 300ms = SLOW
    }, delay);

    return () => {
        clearTimeout(startTimeout);
        if (interval) clearInterval(interval);
    };
  }, [path.length, delay]);

  useEffect(() => {
    if (path && path[index]) {
        setPos(path[index]);
        if (index < path.length - 1) {
            const p1 = path[index];
            const p2 = path[index + 1];
            const dy = p2[0] - p1[0];
            const dx = p2[1] - p1[1];
            setAngle(Math.atan2(dy, dx) * (180 / Math.PI));
        }
    }
  }, [index, path]);

  if (!pos) return null;

  return (
    <Marker 
      position={pos} 
      icon={L.divIcon({
        className: 'moving-chevron',
        html: `<div style="font-size: 14px; font-weight: 900; color: #3b82f6; text-shadow: 0 0 10px #3b82f6; transform: rotate(${-angle}deg); transform-origin: center; white-space: nowrap;">&gt;&gt;&gt;</div>`,
        iconSize: [24, 14],
        iconAnchor: [12, 7]
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
      for (let i=0; i<pointArray.length-1; i++) {
         const p1 = getLatLng(pointArray[i]);
         const p2 = getLatLng(pointArray[i+1]);
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
      if (data.routes) {
        const routesArray = Object.entries(data.routes).map(([zoneId, route]) => ({
          from: zoneId,
          to: route.to_zone,
          path: route.path,
          humans: Math.floor(Math.random() * 200) + 50,
          status: route.status
        }));
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
              setOsrmCache(prev => ({...prev, [key]: mapped}));
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
        for(let i=0; i<r.path.length-1; i++) {
           const start = getLatLng(r.path[i]);
           const end = getLatLng(r.path[i+1]);
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
                         weight={isTopRoute ? 4 : 3} 
                         opacity={0.9}
                         dashArray={isTopRoute ? "10, 10" : "none"}
                         className={isTopRoute ? "best-path-glow" : ""}
                      >
                         <Popup className="custom-popup">
                            <div className="p-1">
                               <div className="text-[10px] font-black text-primary uppercase">OPTIMAL PATH FOUND</div>
                               <div className="text-[8px] text-white/60 font-mono">FLOW: {route.humans} HUMAN_UNITS</div>
                            </div>
                         </Popup>
                      </Polyline>

                      {/* Animated Moving Chevrons (>>>) along the best path */}
                      {isTopRoute && (
                        <>
                          <MovingChevron path={pathGeo} delay={0} />
                          <MovingChevron path={pathGeo} delay={1500} />
                          <MovingChevron path={pathGeo} delay={3000} />
                        </>
                      )}
                    </React.Fragment>
                  );
               })}

               {/* Render Zones (Markers) */}
               {Object.entries(GEO_COORDS).filter(([k]) => k.startsWith('Z')).map(([id, coord]) => {
                  const zone = cityData.zones.find(z => z.id === id);
                  const zoneName = zone?.name || id;
                  return (
                    <Marker key={id} position={coord} icon={zoneIcon}>
                      <Popup className="custom-popup">
                        <div className="p-1">
                          <div className="text-[10px] font-black text-primary tracking-widest uppercase mb-1">{zoneName}</div>
                          <div className="text-[8px] text-gray-400 font-mono">POP: {zone?.population?.toLocaleString()}</div>
                          <div className="text-[8px] text-gray-400 font-mono">RISK: {zone?.flood_risk_base}</div>
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

           <div className="absolute bottom-6 left-6 flex flex-col gap-1 pointer-events-none z-[1000]">
            <span className="text-[12px] font-black text-black tracking-[0.4em] uppercase bg-primary px-2 py-0.5 shadow-lg">BENGALURU_METRO</span>
            <span className="text-[8px] font-mono text-primary bg-black/80 px-2 py-0.5 tracking-[0.2em] uppercase">Geo_Tactical_Overlay_Enabled</span>
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
                      <span className="text-[10px] font-bold text-gray-100">{route.from} ➔ {route.to.slice(0,3)}</span>
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

