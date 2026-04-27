import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminRoute from "./components/AdminRoute";
import Login from "./pages/Login";
import LiveScan from "./pages/LiveScan";
import Seeding from "./pages/Seeding";
import Settings from "./pages/Settings";
import ChangePassword from "./pages/ChangePassword";
import AdminUsers from "./pages/AdminUsers";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/live-scan" replace />} />
          <Route path="/live-scan" element={<LiveScan />} />
          <Route path="/seeding" element={<Seeding />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/change-password" element={<ChangePassword />} />
          <Route element={<AdminRoute />}>
            <Route path="/admin/users" element={<AdminUsers />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
