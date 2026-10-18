import { BrowserRouter, Routes, Route } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/ImportPage";
import ResultsPage from "./pages/ResultsPage";
import DynamicPricesPage from "./pages/DynamicPricesPage";
import ProfilePage from "./pages/ProfilePage";
import "./index.css";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

function App() {
  const routes = (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/upload" element={<ImportPage />} />
            <Route path="/results" element={<ResultsPage />} />
            <Route path="/prices" element={<DynamicPricesPage />} />
          </Route>
        </Route>
      </Routes>
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
