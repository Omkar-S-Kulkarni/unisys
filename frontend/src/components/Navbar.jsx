import { useGlobalSocket } from "../context/SocketContext";

export default function Navbar() {
  const { sendCommand, simulationState } = useGlobalSocket();
  const { scenario, isRunning } = simulationState || {};

  const handleScenarioChange = (newScenario) => {
    sendCommand("CHANGE_SCENARIO", newScenario);
  };

  const handleControl = (controlType) => {
    sendCommand(controlType, null);
  };

  const activeClass = "bg-primary text-black px-3 py-1 text-[10px] font-black tracking-wider shadow-[0_0_15px_rgba(170,255,220,0.3)] transition-all cursor-pointer";
  const inactiveClass = "border border-gray-800 px-3 py-1 text-[10px] font-bold text-gray-500 hover:text-white hover:border-gray-600 cursor-pointer transition-all";

  return (
    <header className="flex justify-between items-center w-full px-6 py-3 border-b border-primary/10 bg-[#0e0e10] backdrop-blur-md sticky top-0 z-50">

      {/* LEFT SIDE */}
      <div className="flex items-center gap-8">
        {/* Logo */}
        <div className="flex flex-col -space-y-1">
          <span className="text-xl font-black tracking-[0.2em] text-primary">
            ADEO
          </span>
          <span className="text-[7px] text-gray-600 font-mono tracking-[0.3em] font-bold">
            V.1.7_ORCHESTRATOR
          </span>
        </div>

        {/* Toggle */}
        <div className="flex bg-[#121214] border border-gray-800 p-0.5 rounded-sm">
          <button className="px-3 py-1 text-[10px] font-bold text-primary bg-primary/10 rounded-sm">
            SYNTHETIC
          </button>
          <button className="px-3 py-1 text-[10px] font-bold text-gray-500 hover:text-white transition-colors">
            REAL
          </button>
        </div>

        {/* Disaster Types */}
        <div className="flex gap-1.5 items-center">
          <span 
            onClick={() => handleScenarioChange("moderate_flood")}
            className={scenario === "moderate_flood" ? activeClass : inactiveClass}>
            MODERATE FLOOD
          </span>
          <span 
            onClick={() => handleScenarioChange("severe_flood")}
            className={scenario === "severe_flood" ? activeClass : inactiveClass}>
            SEVERE FLOOD
          </span>
          <span 
            onClick={() => handleScenarioChange("heatwave")}
            className={scenario === "heatwave" ? activeClass : inactiveClass}>
            HEATWAVE
          </span>
        </div>
      </div>

      {/* RIGHT SIDE */}
      <div className="flex items-center gap-6">
        {/* Controls */}
        <div className="flex items-center gap-3 border-r border-gray-800 pr-6">
          <button 
            onClick={() => handleControl("PLAY_SIMULATION")}
            className={`transition-colors scale-90 ${isRunning ? "text-primary" : "text-gray-400 hover:text-[#aaffdc]"}`}>
            ▶
          </button>
          <button 
            onClick={() => handleControl("PAUSE_SIMULATION")}
            className={`transition-colors scale-90 ${!isRunning ? "text-primary" : "text-gray-400 hover:text-[#aaffdc]"}`}>
            ❚❚
          </button>
          <button 
            onClick={() => handleControl("STEP_SIMULATION")}
            className="text-gray-400 hover:text-[#aaffdc] transition-colors scale-90 font-bold px-1"
            title="Step Forward">
            +1
          </button>
          <button className="text-gray-400 hover:text-[#aaffdc] transition-colors scale-90 text-sm border-l border-gray-800 pl-3">
            ?
          </button>
        </div>

        {/* Icons */}
        <div className="flex items-center gap-5">
           <span className="text-gray-400 cursor-pointer hover:text-white transition-colors text-base">
            ⚙
          </span>
          <div className="relative">
            <span className="text-gray-400 cursor-pointer hover:text-white transition-colors text-base">
              🔔
            </span>
            <span className="absolute -top-1 -right-1 w-2 h-2 bg-orange-500 border border-[#0e0e10] rounded-full shadow-[0_0_8px_rgba(251,146,60,0.4)]"></span>
          </div>
        </div>

        {/* Avatar */}
        <div className="w-9 h-9 border border-gray-800 bg-gray-900/50 flex items-center justify-center grayscale opacity-80 hover:grayscale-0 hover:opacity-100 transition-all cursor-pointer">
           <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=Felix&backgroundColor=454545" alt="Avatar" className="w-full h-full p-1" />
        </div>
      </div>
    </header>
  );
}