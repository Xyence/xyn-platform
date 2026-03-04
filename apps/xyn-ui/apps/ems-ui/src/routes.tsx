import { Routes, Route } from "react-router-dom";
import Login from "./auth/Login";
import Callback from "./auth/Callback";
import DeviceList from "./devices/DeviceList";
import Reports from "./reports/Reports";

export default function RoutesView() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/auth/callback" element={<Callback />} />
      <Route path="/devices" element={<DeviceList />} />
      <Route path="/reports" element={<Reports />} />
    </Routes>
  );
}
