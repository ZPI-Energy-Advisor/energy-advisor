import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { SESSION_EXPIRED_EVENT, isAuthenticated } from "../api/client";

function SessionExpiredListener() {
  const navigate = useNavigate();

  useEffect(() => {
    const handleSessionExpired = () => {
      const { pathname, search, hash } = window.location;
      // Kilka równoległych zapytań może zgłosić wygaśnięcie - przekierowujemy tylko raz.
      if (pathname === "/") {
        return;
      }

      navigate("/", {
        replace: true,
        state: { sessionExpired: true, from: { pathname, search, hash } },
      });
    };

    const handleStorage = (event) => {
      if ((event.key === "access_token" || event.key === null) && !isAuthenticated()) {
        handleSessionExpired();
      }
    };

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
      window.removeEventListener("storage", handleStorage);
    };
  }, [navigate]);

  return null;
}

export default SessionExpiredListener;
