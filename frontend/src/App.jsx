import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/ImportPage";
import TariffsPage from "./pages/TariffsPage";
import SchedulePage from "./pages/SchedulePage";
import DynamicPricesPage from "./pages/DynamicPricesPage";
import PvPage from "./pages/PvPage";
import ProfilePage from "./pages/ProfilePage";
import HomePage from "./pages/HomePage";
import PlanningPage from "./pages/PlanningPage";
import PrivacyPolicyPage from "./pages/PrivacyPolicyPage";
import "./index.css";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import SessionExpiredListener from "./components/SessionExpiredListener";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/privacy" element={<PrivacyPolicyPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/upload" element={<ImportPage />} />
          <Route path="/tariffs" element={<TariffsPage />} />
          <Route path="/results" element={<Navigate to="/tariffs" replace />} />
          <Route path="/calculations" element={<Navigate to="/tariffs" replace />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/prices" element={<DynamicPricesPage />} />
          <Route path="/pv" element={<PvPage />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/plan" element={<PlanningPage />} />
        </Route>
      </Route>
    </Routes>
  );
}

function App() {
  const routes = (
    <BrowserRouter>
      <SessionExpiredListener />
      <AppRoutes />
    </BrowserRouter>
  );

  if (!GOOGLE_CLIENT_ID) {
    return routes;
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      {routes}
    </GoogleOAuthProvider>
  );
}

export default App;
