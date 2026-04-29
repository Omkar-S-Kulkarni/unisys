import React from 'react';
import cityData from '../data/city-model.json';
import { useGlobalSocket } from '../context/SocketContext';

export default function ShelterStatus() {
  const { data } = useGlobalSocket();
  const evacPlan = data?.evacuation_plan || null;
  const liveShelters = data?.city_model?.shelters || cityData.shelters;
  const liveZones = data?.city_model?.zones || cityData.zones;

  // Map incoming zones to shelters based on current plan
  const incomingToShelter = {};
  const incomingPopToShelter = {};

  if (evacPlan && evacPlan.evacuation_sequence) {
    evacPlan.evacuation_sequence.forEach(order => {
      if (order.assigned_shelter) {
        if (!incomingToShelter[order.assigned_shelter]) {
          incomingToShelter[order.assigned_shelter] = [];
          incomingPopToShelter[order.assigned_shelter] = 0;
        }

        // Use the incremental batch size from the backend
        const batchSize = order.next_batch_size || 0;

        if (batchSize > 0) {
          incomingToShelter[order.assigned_shelter].push(`${order.zone_name} (+${batchSize})`);
          incomingPopToShelter[order.assigned_shelter] += batchSize;
        }
      }
    });
  }

  return (
    <div className="flex flex-col h-full space-y-6">
      <div className="flex items-center justify-between border-b border-gray-800 pb-2">
        <div className="flex items-center gap-4">
          <span className="text-xs font-bold text-primary tracking-[0.2em] uppercase">
            Shelter Capacities & Allocation
          </span>
          <div className="h-4 w-px bg-gray-800"></div>
          <span className="text-[10px] font-mono text-gray-500 uppercase tracking-widest">
            Decision_Governor
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-6">
        {liveShelters.map(shelter => {
          const incomingPop = incomingPopToShelter[shelter.id] || 0;
          const projectedOcc = shelter.current_occupancy + incomingPop;
          const percentage = Math.min(Math.round((projectedOcc / shelter.capacity) * 100), 100);

          let barColor = 'bg-emerald-500';
          if (percentage > 90) barColor = 'bg-red-500';
          else if (percentage > 60) barColor = 'bg-orange-500';

          return (
            <div key={shelter.id} className="bg-[#111114] border border-gray-800/50 flex flex-col p-6 relative overflow-hidden group">
              {/* Background subtle mesh */}
              <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none text-9xl">🏛️</div>

              <div className="flex justify-between items-start mb-6">
                <div>
                  <h2 className="text-2xl font-black text-gray-100 uppercase tracking-wide group-hover:text-primary transition-colors">
                    {shelter.name}
                  </h2>
                  <span className="text-xs text-gray-500 font-mono tracking-widest">ID: {shelter.id} | SECTOR_ALPHA</span>
                </div>
                {shelter.has_medical && (
                  <div className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold uppercase tracking-wider rounded-sm">
                    + Medical Wing (Active)
                  </div>
                )}
              </div>

              <div className="grid grid-cols-3 gap-8 mb-6">
                <div>
                  <div className="text-[10px] text-gray-500 font-bold uppercase tracking-[0.1em] mb-1">Max Capacity</div>
                  <div className="text-xl font-mono text-gray-300">{shelter.capacity.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-[10px] text-gray-500 font-bold uppercase tracking-[0.1em] mb-1">Live Occupancy</div>
                  <div className="text-xl font-mono text-gray-300">{shelter.current_occupancy.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-[0.1em] mb-1 text-primary">Active Inbound</div>
                  <div className="text-xl font-mono font-bold text-primary">+{incomingPop.toLocaleString()} Citizens</div>
                </div>
              </div>

              <div className="mb-2 flex justify-between items-end">
                <span className="text-xs text-gray-400 font-bold uppercase tracking-widest">Projected Load Factor</span>
                <span className={`text-2xl font-black font-mono ${percentage > 90 ? 'text-red-500' : 'text-gray-200'}`}>
                  {percentage}%
                </span>
              </div>

              {/* Thick Progress Bar */}
              <div className="h-4 bg-[#1a1a20] rounded-sm overflow-hidden border border-gray-800 shadow-inner">
                <div className={`h-full ${barColor} shadow-[0_0_10px_rgba(255,255,255,0.1)] transition-all duration-1000 ease-out`} style={{ width: `${percentage}%` }}></div>
              </div>

              {/* Inbound Routing Log */}
              <div className="mt-8 pt-4 border-t border-gray-800/50">
                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3 block">Extraction Source Points</span>
                <div className="flex flex-wrap gap-2">
                  {incomingToShelter[shelter.id] && incomingToShelter[shelter.id].length > 0 ? (
                    incomingToShelter[shelter.id].map((tag, idx) => (
                      <div key={idx} className="bg-white/5 border border-white/10 px-3 py-1.5 text-xs text-gray-300 font-mono rounded flex items-center gap-2">
                        <span className="text-primary">←</span> {tag.replace(' ', '_')}
                      </div>
                    ))
                  ) : (
                    <span className="text-xs text-gray-600 italic">No active extraction batches routing to this hub.</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}