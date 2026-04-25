import React, { useState, useEffect } from 'react';
import cityData from '../data/city-model.json';
import { useGlobalSocket } from '../context/SocketContext';

const getRiskConfig = (risk) => {
  if (risk >= 9) return { label: 'CRITICAL', color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/50', bar: 'bg-red-500', action: 'EVACUATE' };
  if (risk >= 7) return { label: 'HIGH', color: 'text-orange-500', bg: 'bg-orange-500/10', border: 'border-orange-500/50', bar: 'bg-orange-500', action: 'STANDBY' };
  if (risk >= 4) return { label: 'MOD', color: 'text-yellow-500', bg: 'bg-yellow-500/10', border: 'border-yellow-500/50', bar: 'bg-yellow-500', action: 'STANDBY' };
  return { label: 'STABLE', color: 'text-emerald-500', bg: 'bg-emerald-500/10', border: 'border-emerald-500/50', bar: 'bg-emerald-500', action: 'SAFE' };
};

const ZoneCard = ({ zone, liveRisk }) => {
  const risk = liveRisk !== undefined ? liveRisk : zone.flood_risk_base;
  const config = getRiskConfig(risk);

  return (
    <div className={`p-4 border-l-2 ${config.border} bg-[#16161a] hover:bg-[#1c1c21] transition-all group cursor-pointer`}>
      <div className="flex justify-between items-start mb-2">
        <span className="text-[10px] text-gray-500 font-mono tracking-tighter">ZONE_{zone.id.replace('Z', '0')}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-sm ${config.bg} ${config.color} border border-current/20`}>
          {config.label}
        </span>
      </div>
      <div className="text-sm font-bold text-gray-200 uppercase tracking-wide mb-1 truncate">
        {zone.name.replace(' ', '_')}
      </div>
      <div className="flex items-end justify-between">
        <div className="text-2xl font-black text-gray-100 font-mono leading-none">
          {risk?.toFixed(1) || "0.0"}
        </div>
        <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest pb-1 self-end group-hover:text-gray-300">
          {config.action}
        </div>
      </div>
      {/* Decorative mini bar at bottom */}
      <div className="mt-3 h-0.5 bg-gray-800 w-full overflow-hidden">
        <div className={`h-full ${config.bar} transition-all duration-700`} style={{ width: `${Math.min(100, risk * 10)}%` }}></div>
      </div>
    </div>
  );
};

export default function Orchestration() {
  const { data, sendCommand, globalLogs } = useGlobalSocket();
  const [tick, setTick] = useState(0);
  const [zones] = useState(cityData.zones);
  const [riskScores, setRiskScores] = useState({});
  const [evacPlan, setEvacPlan] = useState(null);
  const [zoneStates, setZoneStates] = useState([]);
  const [selectedRoad, setSelectedRoad] = useState('');

  useEffect(() => {
    if (data && data.tick !== undefined) {
      setTick(data.tick);

      if (data.risk_scores) {
        setRiskScores(data.risk_scores);
      }

      if (data.evacuation_plan) {
        setEvacPlan(data.evacuation_plan);
      }

      if (data.zone_states) {
        setZoneStates(data.zone_states);
      }
    }
  }, [data]);

  const getLiveRisk = (zone) => {
    const rs = riskScores[zone.name];
    return rs !== undefined ? rs : undefined;
  };

  const evacSequence = evacPlan?.evacuation_sequence || [];
  const topEvacOrders = evacSequence.slice(0, 5);

  const vulnerabilityRanked = [...zoneStates]
    .sort((a, b) => (b.vulnerability_score || 0) - (a.vulnerability_score || 0))
    .slice(0, 5);

  const shelterUsage = {};
  for (const entry of evacSequence) {
    if (entry.assigned_shelter) {
      shelterUsage[entry.assigned_shelter] = (shelterUsage[entry.assigned_shelter] || 0) + 1;
    }
  }
  const sheltersFromModel = cityData.shelters || [];

  const handleManualOverride = () => {
    if (!selectedRoad) return;
    const parts = selectedRoad.split("|");
    if (parts.length === 2) {
       sendCommand("MANUAL_BLOCK", {
           from: parts[0],
           to: parts[1],
           reason: "Human Evaluator Override via Dashboard"
       });
       setSelectedRoad('');
    }
  };

  return (
    <div className="flex flex-col h-full space-y-6">
      <div className="flex items-center justify-between border-b border-gray-800 pb-2">
        <div className="flex items-center gap-4">
          <span className="text-xs font-bold text-primary tracking-[0.2em] uppercase">
            Decision Governor: ACTIVE
          </span>
          <div className="h-4 w-px bg-gray-800"></div>
          <span className="text-[10px] font-mono text-gray-500 uppercase tracking-widest">
            Live_Tick: {tick}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
            <span className="text-[10px] text-gray-400 font-bold uppercase">CONNECTED</span>
          </div>
          <div className="text-[10px] font-mono text-gray-500 tracking-widest">
            REFRESH: 2s
          </div>
        </div>
      </div>

      <div className="flex flex-1 gap-6 overflow-hidden">
        <div className="flex-[3] flex flex-col gap-6 overflow-y-auto no-scrollbar">

          <div className="grid grid-cols-4 gap-4">
            {zones.map(zone => (
              <ZoneCard key={zone.id} zone={zone} liveRisk={getLiveRisk(zone)} />
            ))}
          </div>

          <div className="grid grid-cols-2 gap-6 h-64 min-h-[16rem]">
            <div className="flex flex-col border border-gray-800/50 bg-[#111114]">
              <div className="px-4 py-2 border-b border-gray-800 flex items-center justify-between">
                <span className="text-[10px] font-bold text-gray-400 tracking-[0.1em] uppercase">Evacuation Orders (Live)</span>
                <span className="text-[10px] text-emerald-500 font-mono">{evacSequence.length} zones</span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3 font-mono">
                {topEvacOrders.length > 0 ? (
                  topEvacOrders.map((order, i) => {
                    const statusColor = order.assigned_route ? 'text-emerald-400' : 'text-orange-400';
                    const statusLabel = order.assigned_route ? 'ROUTING' : 'NO ROUTE';
                    return (
                      <div key={i} className="flex items-center gap-4 text-[11px] group cursor-pointer hover:bg-white/5 p-1 -m-1 rounded">
                        <span className="text-red-500 font-bold w-4">{order.rank}</span>
                        <div className="flex-1 flex items-center gap-2">
                          <span className="font-bold text-gray-300 uppercase">{order.zone_name}</span>
                          <span className="text-gray-600 text-[10px]">-&gt;</span>
                          <span className="font-bold text-gray-300">{order.assigned_shelter || '---'}</span>
                        </div>
                        <span className="text-gray-500 font-mono text-[9px]">{order.priority_score.toFixed(2)}</span>
                        <span className={`font-bold ${statusColor} text-[9px] tracking-tighter`}>{statusLabel}</span>
                      </div>
                    );
                  })
                ) : (
                  <div className="text-[11px] text-gray-600 italic">Waiting for simulation data...</div>
                )}
              </div>
            </div>

            <div className="flex flex-col border border-gray-800/50 bg-[#111114]">
              <div className="px-4 py-2 border-b border-gray-800 flex items-center justify-between">
                <span className="text-[10px] font-bold text-gray-400 tracking-[0.1em] uppercase">Decision Log</span>
                <span className="text-[10px] text-gray-500 font-mono">{globalLogs.length} entries</span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-2 font-mono">
                {globalLogs.length > 0 ? (
                  globalLogs.slice(0, 20).map((log, i) => (
                    <div key={i} className="flex gap-3 text-[10px] leading-relaxed">
                      <span className="text-emerald-500/60 shrink-0">{log.time}</span>
                      <span className={log.color}>{log.msg}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-[10px] text-gray-600 italic">Waiting for tick data...</div>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col gap-6">

          <div className="flex flex-col border border-gray-800/50 bg-[#111114]">
            <div className="px-4 py-2 border-b border-gray-800">
              <span className="text-[10px] font-bold text-gray-400 tracking-[0.1em] uppercase">Manual Override</span>
            </div>
            <div className="p-4 flex flex-col gap-3">
              <p className="text-[10px] text-gray-500 tracking-wide mb-1">Select a route to mark as impassable.</p>
              <select 
                value={selectedRoad}
                onChange={(e) => setSelectedRoad(e.target.value)}
                className="w-full bg-[#16161a] border border-gray-700 text-gray-300 text-xs p-2 rounded focus:outline-none focus:border-red-500">
                <option value="">-- Select Road Segment --</option>
                {cityData.road_network.edges.map((edge, i) => {
                    // Extract names from Zone IDs by looking up
                    const z1 = cityData.zones.find(z => z.id === edge[0])?.name || edge[0];
                    const z2 = cityData.zones.find(z => z.id === edge[1])?.name || edge[1];
                    return (
                        <option key={i} value={`${z1}|${z2}`}>{edge[3]}</option>
                    )
                })}
              </select>
              <button 
                onClick={handleManualOverride}
                disabled={!selectedRoad}
                className="w-full bg-red-600/20 text-red-500 border border-red-600/50 hover:bg-red-600 hover:text-white transition-all text-[10px] font-bold tracking-widest py-2 rounded uppercase disabled:opacity-50 disabled:cursor-not-allowed">
                Trigger Replan / Flood Route
              </button>
            </div>
          </div>

          <div className="flex flex-col border border-gray-800/50 bg-[#111114]">
            <div className="px-4 py-2 border-b border-gray-800">
              <span className="text-[10px] font-bold text-gray-400 tracking-[0.1em] uppercase">Vulnerability Ranking</span>
            </div>
            <div className="p-4 overflow-x-auto">
              <table className="w-full text-left text-[10px] font-mono">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800 pb-1">
                    <th className="font-normal py-1 uppercase">RN</th>
                    <th className="font-normal py-1 uppercase">Zone</th>
                    <th className="font-normal py-1 uppercase">Risk</th>
                    <th className="font-normal py-1 text-right uppercase">Vuln</th>
                  </tr>
                </thead>
                <tbody className="text-gray-400">
                  {vulnerabilityRanked.length > 0 ? (
                    vulnerabilityRanked.map((row, i) => (
                      <tr key={i} className="hover:bg-white/5 group transition-colors">
                        <td className="py-2 text-red-500 font-bold">{String(i + 1).padStart(2, '0')}</td>
                        <td className="py-2 font-bold group-hover:text-white uppercase">{row.zone_name}</td>
                        <td className="py-2 font-mono">{(row.risk_score || 0).toFixed(1)}</td>
                        <td className="py-2 text-right font-bold group-hover:text-white">{(row.vulnerability_score || 0).toFixed(1)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan="4" className="py-4 text-gray-600 italic text-center">Awaiting data...</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex flex-col border border-gray-800/50 bg-[#111114]">
            <div className="px-4 py-2 border-b border-gray-800">
              <span className="text-[10px] font-bold text-gray-400 tracking-[0.1em] uppercase">Shelter Occupancy</span>
            </div>
            <div className="p-4 space-y-5">
              {sheltersFromModel.map((shelter, i) => {
                const assigned = shelterUsage[shelter.id] || 0;
                const occ = shelter.current_occupancy + assigned;
                const pct = shelter.capacity > 0 ? Math.min(Math.round((occ / shelter.capacity) * 100), 100) : 0;
                const barColor = pct > 90 ? 'bg-red-400' : pct > 60 ? 'bg-orange-400' : 'bg-emerald-400';
                return (
                  <div key={i} className="space-y-1.5">
                    <div className="flex justify-between items-center text-[10px] font-mono">
                      <span className="text-gray-300 font-bold uppercase">{shelter.name}</span>
                      <span className="text-gray-500 font-bold tracking-tighter">{pct}%</span>
                    </div>
                    <div className="h-1 bg-gray-800 w-full overflow-hidden rounded-full">
                      <div className={`h-full ${barColor} transition-all duration-1000`} style={{ width: `${pct}%` }}></div>
                    </div>
                    <div className="text-[9px] text-gray-600 font-mono tracking-tighter">
                      {occ} / {shelter.capacity} CAPACITY
                      {shelter.has_medical && <span className="ml-2 text-emerald-500">+ MEDICAL</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}