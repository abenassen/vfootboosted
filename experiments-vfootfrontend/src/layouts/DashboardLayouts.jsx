import HaderReact from '@/Navbar';
import { Outlet } from "react-router-dom";

export default function DashboardLayout() {
  return (
    <div>
      <HaderReact />
      <div className="pt-20"> {/* Padding-top per non sovrapporre la navbar */}
        <Outlet />
      </div>
    </div>
  );
}
