import Navbar from "./components/Navbar";
import Sidebar from "./components/Sidebar";
import { Routes, Route } from "react-router-dom";
import Orchestration from "./pages/Orchestration";
import ZonalAnalysis from "./pages/ZonalAnalysis";
import ShelterStatus from "./pages/ShelterStatus";
import ReplanLog from "./pages/ReplanLog";
import RoutePlan from "./pages/RoutePlan";
import { SocketProvider } from "./context/SocketContext";

export default function App() {
  return (
    <SocketProvider>
      <div className="h-screen bg-[#0e0e10] text-white flex flex-col overflow-hidden">

        {/* Top Navbar */}
        <Navbar />

        {/* Main Layout */}
        <div className="flex flex-1 overflow-hidden">

          {/* Sidebar */}
          <Sidebar />

          {/* Page Content */}
          <main className="p-6 flex-1 overflow-y-auto no-scrollbar bg-[#0e0e10]">
            <Routes>
              <Route path="/" element={<Orchestration />} />
              <Route path="/route-plan" element={<RoutePlan />} />
              <Route path="/zonal" element={<ZonalAnalysis />} />
              <Route path="/shelter" element={<ShelterStatus />} />
              <Route path="/replan" element={<ReplanLog />} />
            </Routes>
          </main>

        </div>

      </div>
    </SocketProvider>
  );
}