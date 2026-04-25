import React, { useState, useEffect } from 'react';
import cityData from '../data/city-model.json';
import { useGlobalSocket } from '../context/SocketContext';

export default function ZonalAnalysis() {
  const { data } = useGlobalSocket();
  const [zoneStates, setZoneStates] = useState([]);
  const [riskScores, setRiskScores] = useState({});

  useEffect(() => {
    if (data && data.zone_states) {
      setZoneStates(data.zone_states);
    }
    if (data && data.risk_scores) {
      setRiskScores(data.risk_scores);
    }
  }, [data]);

  // Merge static demographic data with live state
  const mergedZones = cityData.zones.map(baseZone => {
    const liveState = zoneStates.find(z => z.zone_name === baseZone.name) || {};
    const risk = riskScores[baseZone.name] !== undefined ? riskScores[baseZone.name] : baseZone.flood_risk_base;
    return {
      ...baseZone,
      vulnerability_score: liveState.vulnerability_score || 0,
      risk_score: risk
    };
  });

  // Sort by vulnerability descending
  mergedZones.sort((a, b) => b.vulnerability_score - a.vulnerability_score);

  const highestRiskZone = [...mergedZones].sort((a, b) => b.risk_score - a.risk_score)[0];
  const highestVulnZone = mergedZones[0];
  const avgRisk = mergedZones.length > 0 
    ? (mergedZones.reduce((acc, z) => acc + z.risk_score, 0) / mergedZones.length).toFixed(1)
    : "0.0";

  return (
    <div className="flex flex-col h-full space-y-6">
      {/* Header Info */}
      <div className="flex items-center justify-between border-b border-gray-800 pb-2">
         <div className="flex items-center gap-4">
          <span className="text-xs font-bold text-primary tracking-[0.2em] uppercase">
            Zonal Deep Dive
          </span>
          <div className="h-4 w-px bg-gray-800"></div>
          <span className="text-[10px] font-mono text-gray-500 uppercase tracking-widest">
            Vulnerability_Prioritization_Agent
          </span>
        </div>
      </div>

      {/* Top Value Cards */}
      <div className="grid grid-cols-3 gap-6">
        <div className="bg-[#111114] border border-gray-800/50 p-4">
           <span className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.1em]">Average City Risk</span>
           <div className="text-3xl font-black text-gray-200 mt-2 font-mono">{avgRisk} <span className="text-[12px] text-gray-600 font-normal">/ 10</span></div>
        </div>
        <div className="bg-[#111114] border border-gray-800/50 p-4">
           <span className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.1em]">Highest Risk Zone</span>
           <div className="text-3xl font-black text-red-500 mt-2">{highestRiskZone?.name || 'N/A'}</div>
        </div>
        <div className="bg-[#111114] border border-gray-800/50 p-4">
           <span className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.1em]">Most Vulnerable</span>
           <div className="text-3xl font-black text-orange-400 mt-2">{highestVulnZone?.name || 'N/A'}</div>
        </div>
      </div>

      {/* Main Table */}
      <div className="flex-1 bg-[#111114] border border-gray-800/50 flex flex-col overflow-hidden">
         <div className="px-4 py-3 border-b border-gray-800">
            <span className="text-[10px] font-bold text-white tracking-[0.1em] uppercase">Zone Specifications & Live Tracking</span>
         </div>
         <div className="flex-1 overflow-x-auto overflow-y-auto">
            <table className="w-full text-left text-xs font-mono">
               <thead className="bg-[#16161a] sticky top-0">
                 <tr className="text-gray-500 border-b border-gray-800">
                    <th className="font-normal py-3 px-4 uppercase tracking-widest">Zone ID</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest">Name</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest text-right">Population</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest text-right">Elderly %</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest text-center">Hospital</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest text-right text-orange-400">Vuln Score</th>
                    <th className="font-normal py-3 px-4 uppercase tracking-widest text-right text-red-400">Risk Score</th>
                 </tr>
               </thead>
               <tbody className="text-gray-300">
                  {mergedZones.map((zone, i) => (
                    <tr key={zone.id} className="border-b border-gray-800/50 hover:bg-white/5 transition-colors">
                       <td className="py-3 px-4 text-emerald-400">{zone.id}</td>
                       <td className="py-3 px-4 font-bold uppercase">{zone.name}</td>
                       <td className="py-3 px-4 text-right text-gray-400">{zone.population.toLocaleString()}</td>
                       <td className="py-3 px-4 text-right">{zone.elderly_percent}%</td>
                       <td className="py-3 px-4 text-center">{zone.has_hospital ? '🏥' : '-'}</td>
                       <td className="py-3 px-4 text-right font-black text-orange-300">{zone.vulnerability_score.toFixed(2)}</td>
                       <td className="py-3 px-4 text-right font-black text-red-300 relative">
                           {zone.risk_score.toFixed(1)}
                           <div className="absolute bottom-0 right-4 h-0.5 bg-red-500/50" style={{ width: `${zone.risk_score * 10}%` }}></div>
                       </td>
                    </tr>
                  ))}
               </tbody>
            </table>
         </div>
      </div>
    </div>
  );
}