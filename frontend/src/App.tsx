import { Routes, Route } from "react-router-dom";
import AppLayout from "./components/Layout";
import Home from "./pages/Home";
import LiveScan from "./pages/LiveScan";

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/live-scan" element={<LiveScan />} />
      </Route>
    </Routes>
  );
}

export default App;
