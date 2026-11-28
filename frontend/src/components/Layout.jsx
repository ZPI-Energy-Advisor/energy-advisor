import { useEffect, useState } from "react";
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
  FiClock,
  FiZap,
  FiCalendar,
  FiSun,
} from "react-icons/fi";
import apiClient, { clearAuth } from "../api/client";
import { EnergyFileProvider } from "../context/EnergyFileProvider";
import { CurrentUserProvider } from "../context/CurrentUserProvider";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import logo from "../assets/logo/logo.svg";
import PrivacyPolicyAcceptance from "./PrivacyPolicyAcceptance";
import { PRIVACY_POLICY_PATH, acceptPrivacyPolicy } from "../api/privacyPolicy";

const icon = (Icon) => <Icon aria-hidden="true" className="mr-3 text-lg" />;

// Menu w kolejności pracy: najpierw dane, potem analiza, na końcu dom Smart Home (ZP-124).
// `show` decyduje, czy pozycja jest w menu; tytuł karty przeglądarki bierze nazwę z pełnej listy.
const NAV_GROUPS = [
  {
    label: "Dane",
    items: [
      { path: "/profile", label: "Profil", icon: icon(FiUser) },
      { path: "/upload", label: "Import danych", icon: icon(FiUploadCloud) },
    ],
  },
  {
    label: "Analiza",
    items: [
      { path: "/dashboard", label: "Pulpit", icon: icon(FiHome) },
      { path: "/tariffs", label: "Taryfy", icon: icon(FiPieChart) },
      { path: "/prices", label: "Ceny dynamiczne", icon: icon(FiTrendingUp) },
      { path: "/pv", label: "Fotowoltaika", icon: icon(FiSun), show: (me) => Boolean(me?.profile?.has_pv) },
      { path: "/schedule", label: "Optymalizacja", icon: icon(FiClock) },
    ],
  },
  {
    label: "Dom",
    items: [
      // Dom Smart Home ma jednego właściciela (HUB_HOME_USER_EMAIL); pozostali nie widzą „Mój dom”.
      { path: "/home", label: "Mój dom", icon: icon(FiZap), show: (me) => Boolean(me?.home_owner) },
      // Plan na jutro jest dla każdego (urządzenia z pliku); symulację planu uruchamia tylko właściciel domu.
      { path: "/plan", label: "Plan na jutro", icon: icon(FiCalendar) },
    ],
  },
];

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

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
  const { me, refresh } = useCurrentUser();
  // Konto bez akceptacji aktualnej polityki (zmiana wersji albo konto sprzed ZP-129) nie korzysta z aplikacji.
  const needsPolicyAcceptance = Boolean(me?.privacy_policy?.needs_acceptance);

  const navGroups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.show || item.show(me)),
  })).filter((group) => group.items.length > 0);
  useDocumentTitle(ALL_NAV_ITEMS.find((item) => location.pathname.startsWith(item.path))?.label);

  const closeSidebar = () => setIsSidebarOpen(false);

  // Menu na telefonie zamyka się po wyborze pozycji, kliknięciu w tło i klawiszem Escape.
  useEffect(() => {
    if (!isSidebarOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setIsSidebarOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isSidebarOpen]);

  return (
    <div className="flex flex-col md:flex-row h-screen h-dvh bg-gray-50 font-sans text-gray-900 overflow-hidden pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      
      <div className="md:hidden flex items-center justify-between bg-white border-b border-gray-200 p-4 z-20">
        <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight">
          <img src={logo} alt="" className="h-7 w-auto" />
          <span>
            Energy<span className="text-emerald-500">Advisor</span>
          </span>
        </h1>
        <button
          type="button"
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          aria-label={isSidebarOpen ? "Zamknij menu" : "Otwórz menu"}
          aria-expanded={isSidebarOpen}
          aria-controls="app-menu"
          className="p-2 text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
        >
          {isSidebarOpen ? <FiX size={24} aria-hidden="true" /> : <FiMenu size={24} aria-hidden="true" />}
        </button>
      </div>

      {isSidebarOpen && (
        <div 
          className="fixed inset-0 bg-gray-900 bg-opacity-50 z-30 md:hidden transition-opacity"
          onClick={closeSidebar}
        ></div>
      )}

      <div id="app-menu" className={`fixed inset-y-0 left-0 z-40 w-64 pt-[env(safe-area-inset-top)] md:pt-0 bg-white border-r border-gray-200 flex flex-col shadow-lg md:shadow-sm transform transition-transform duration-300 ease-in-out md:relative md:translate-x-0 ${
        isSidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}>
        <div className="p-6 hidden md:block">
          <h1 className="flex items-center gap-3 text-2xl font-bold tracking-tight">
            <img src={logo} alt="" className="h-9 w-auto" />
            <span>
              Energy<span className="text-emerald-500">Advisor</span>
            </span>
          </h1>
        </div>

        <nav aria-label="Menu główne" className="flex-1 mt-6 md:mt-2 overflow-y-auto pb-2">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-3">
              <p id={`nav-${group.label}`} className="px-6 pb-1 pt-2 text-xs font-semibold text-gray-400">
                {group.label}
              </p>
              <ul aria-labelledby={`nav-${group.label}`}>
                {group.items.map((item) => (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      onClick={closeSidebar}
                      aria-current={isActive(item.path) ? "page" : undefined}
                      className={`flex items-center px-6 py-3 text-sm font-medium transition-colors ${
                        isActive(item.path)
                          ? "bg-emerald-50 border-l-4 border-emerald-500 text-emerald-700"
                          : "text-gray-600 hover:bg-gray-50 hover:text-gray-900 border-l-4 border-transparent"
                      }`}
                    >
                      {item.icon}
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="p-4 border-t border-gray-200">
          <Link
            to={PRIVACY_POLICY_PATH}
            target="_blank"
            rel="noopener noreferrer"
            className="block px-4 pb-2 text-xs text-gray-500 hover:text-gray-700 hover:underline"
          >
            Polityka prywatności
          </Link>
          <button
            onClick={handleLogout}
            data-leaves-page
            className="flex items-center w-full px-4 py-3 text-sm font-medium text-red-600 hover:bg-red-50 rounded transition-colors"
          >
            <FiLogOut className="mr-3 text-lg" />
            Wyloguj się
          </button>
        </div>
      </div>

      {/* relative: elementy pozycjonowane absolutnie (np. teksty sr-only, panele) liczą się względem przewijanej treści,
          a nie całego okna; inaczej okno dostaje drugi pasek przewijania. */}
      <div className="relative flex-1 p-4 md:p-10 overflow-y-auto h-full w-full">
        {!needsPolicyAcceptance && <Outlet />}
      </div>

      {needsPolicyAcceptance && (
        <PrivacyPolicyAcceptance
          title="Zmiana polityki prywatności"
          intro="Aby dalej korzystać z Energy Advisora, zapoznaj się z aktualną polityką prywatności i ją zaakceptuj."
          acceptLabel="Akceptuję"
          onAccept={async (version) => {
            await acceptPrivacyPolicy(version);
            await refresh();
          }}
          cancelLabel="Wyloguj się"
          onCancel={handleLogout}
        />
      )}
    </div>
  );
}

// Providery w Layoucie przeżywają przejścia między stronami, więc wybrany plik, jego dane i konto
// użytkownika zostają przy nawigacji. Obejmują też menu, które zależy od konta (Fotowoltaika, Mój dom).
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