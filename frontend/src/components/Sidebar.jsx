import { Link, useLocation } from "react-router-dom";

export default function Sidebar() {
  const location = useLocation();

  const navItems = [
    { label: "Orchestration", path: "/", icon: "grid_view" },
    { label: "Route Plan", path: "/route-plan", icon: "map" },
    { label: "Zonal Analysis", path: "/zonal", icon: "analytics" },
    { label: "Shelter Status", path: "/shelter", icon: "shield" },
    { label: "Replan Log", path: "/replan", icon: "history" }
  ];

  return (
    <aside className="w-64 bg-[#0e0e10] border-r border-primary/10 flex flex-col p-5 sticky left-0 h-[calc(100vh-65px)]">

      {/* Header Info */}
      <div className="mb-10 space-y-1">
        <div className="text-[9px] text-gray-600 uppercase tracking-[0.2em] font-bold font-mono">
          SYSTEM_STATUS_INDICATOR
        </div>
        <div className="text-lg font-black text-primary tracking-tight leading-none">
          KINETIC_COMMAND
        </div>
        <div className="text-[9px] text-gray-500 font-mono">
          SECTOR_7_ACTIVE // AUTH_STP_44
        </div>
      </div>

      <nav className="flex flex-col gap-1.5">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-4 px-4 py-3 transition-all group ${
                isActive 
                ? "bg-primary text-black shadow-[0_0_20px_rgba(170,255,220,0.2)]" 
                : "text-gray-500 hover:text-gray-200 hover:bg-white/5"
              }`}
            >
              <span className={`material-symbols-outlined text-[18px] ${isActive ? "text-black" : "text-gray-400 group-hover:text-primary"}`}>
                {item.icon === "grid_view" && "⊞"}
                {item.icon === "map" && "🗺️"}
                {item.icon === "analytics" && "▥"}
                {item.icon === "shield" && "🛡"}
                {item.icon === "history" && "🕒"}
              </span>
              <span className="text-[10px] font-black uppercase tracking-[0.15em]">
                {item.label}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom Action */}
      <div className="mt-auto pt-6 border-t border-gray-800/50">
        <button className="w-full bg-[#ff716c]/10 text-[#ff716c] border border-[#ff716c]/30 py-3 text-[10px] font-black tracking-[0.2em] uppercase hover:bg-[#ff716c] hover:text-[#0e0e10] transition-all group active:scale-[0.98]">
           EMERGENCY REPLAN
        </button>
      </div>

    </aside>
  );
}