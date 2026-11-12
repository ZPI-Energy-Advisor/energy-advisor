import { useState } from "react";
import { Link, useLocation, Outlet, useNavigate } from "react-router-dom";
import {
  FiHome,
  FiUploadCloud,
  FiPieChart,
  FiTrendingUp,
  FiLogOut,
  FiMenu,
  FiX,
  FiUser,
  FiDollarSign,
  FiClock,
  FiZap,
  FiCalendar,
} from "react-icons/fi";
import apiClient, { clearAuth } from "../api/client";
import { EnergyFileProvider } from "../context/EnergyFileProvider";
import { CurrentUserProvider } from "../context/CurrentUserProvider";
import { useCurrentUser } from "../hooks/useCurrentUser";

const HOME_NAV_ITEM = { path: "/home", label: "Mój dom", icon: <FiZap className="mr-3 text-lg" /> };

function LayoutShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const handleLogout = async () => {
    const refreshToken = localStorage.getItem("refresh_token");

    try {
      if (refreshToken) {
        await apiClient.post("/auth/logout", {
          refresh_token: refreshToken,
        });
      }
    } catch (error) {
      console.error("Nie udało się unieważnić sesji na backendzie.", error);
    } finally {
      clearAuth();
      navigate("/");
    }
  };

  const isActive = (path) => location.pathname === path;
  // Dom Smart Home ma jednego właściciela (HUB_HOME_USER_EMAIL); pozostali nie widzą tej pozycji.
  const { me } = useCurrentUser();

  const navItems = [
    {
      path: "/profile",
      label: "Profil",
      icon: <FiUser className="mr-3 text-lg" />,
    },
    {
      path: "/dashboard",
      label: "Dashboard",
      icon: <FiHome className="mr-3 text-lg" />,
    },
    {
      path: "/upload",
      label: "Import Danych",
      icon: <FiUploadCloud className="mr-3 text-lg" />,
    },
    {
      path: "/results",
      label: "Analiza Taryf",
      icon: <FiPieChart className="mr-3 text-lg" />,
    },
    {
      path: "/calculations",
      label: "Wyniki kalkulacji",
      icon: <FiDollarSign className="mr-3 text-lg" />,
    },
    {
      path: "/prices",
      label: "Ceny dynamiczne",
      icon: <FiTrendingUp className="mr-3 text-lg" />,
    },
    {
      path: "/schedule",
      label: "Optymalizacja",
      icon: <FiClock className="mr-3 text-lg" />,
    },
    {
      path: "/plan",
      label: "Plan na jutro",
      icon: <FiCalendar className="mr-3 text-lg" />,
    },
    ...(me?.home_owner ? [HOME_NAV_ITEM] : []),
  ];

  const closeSidebar = () => setIsSidebarOpen(false);

  return (
    <div className="flex flex-col md:flex-row h-screen bg-gray-50 font-sans text-gray-900 overflow-hidden">
      
      <div className="md:hidden flex items-center justify-between bg-white border-b border-gray-200 p-4 z-20">
        <h1 className="text-xl font-bold tracking-tight">
          Energy<span className="text-emerald-500">Advisor</span>
        </h1>
        <button 
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          className="p-2 text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
        >
          {isSidebarOpen ? <FiX size={24} /> : <FiMenu size={24} />}
        </button>
      </div>

      {isSidebarOpen && (
        <div 
          className="fixed inset-0 bg-gray-900 bg-opacity-50 z-30 md:hidden transition-opacity"
          onClick={closeSidebar}
        ></div>
      )}

      <div className={`fixed inset-y-0 left-0 z-40 w-64 bg-white border-r border-gray-200 flex flex-col shadow-lg md:shadow-sm transform transition-transform duration-300 ease-in-out md:relative md:translate-x-0 ${
        isSidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}>
        <div className="p-6 hidden md:block">
          <h1 className="text-2xl font-bold tracking-tight">
            Energy<span className="text-emerald-500">Advisor</span>
          </h1>
        </div>

        <nav className="flex-1 mt-6 md:mt-2 overflow-y-auto">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              onClick={closeSidebar}
              className={`flex items-center px-6 py-4 text-sm font-medium transition-colors ${
                isActive(item.path)
                  ? "bg-emerald-50 border-l-4 border-emerald-500 text-emerald-700"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900 border-l-4 border-transparent"
              }`}
            >
              {item.icon}
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="p-4 border-t border-gray-200">
          <button
            onClick={handleLogout}
            className="flex items-center w-full px-4 py-3 text-sm font-medium text-red-600 hover:bg-red-50 rounded transition-colors"
          >
            <FiLogOut className="mr-3 text-lg" />
            Wyloguj się
          </button>
        </div>
      </div>

      <div className="flex-1 p-4 md:p-10 overflow-y-auto h-full w-full">
        <Outlet />
      </div>
    </div>
  );
}

// Providery w Layoucie przeżywają przejścia między stronami, więc wybrany plik, jego dane i konto
// użytkownika zostają przy nawigacji. Obejmują też menu, które zależy od konta (pozycja „Mój dom”).
function Layout() {
  return (
    <CurrentUserProvider>
      <EnergyFileProvider>
        <LayoutShell />
      </EnergyFileProvider>
    </CurrentUserProvider>
  );
}

export default Layout;