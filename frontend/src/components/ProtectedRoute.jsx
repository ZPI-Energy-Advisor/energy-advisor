import { Navigate, Outlet } from "react-router-dom";

function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem("user"));
  } catch {
    return null;
  }
}

function ProtectedRoute() {
  const user = getStoredUser();

  if (!user || !user.id || !localStorage.getItem("access_token")) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

export default ProtectedRoute;
