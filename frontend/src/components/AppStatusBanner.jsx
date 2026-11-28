import { useEffect, useState } from "react";
import { FiRefreshCw, FiWifiOff } from "react-icons/fi";
import { buttonClass } from "./uiStyles";

// Tę samą nazwę zdarzenia wysyła pwa/registerServiceWorker.js (bez importu, żeby testy nie ładowały modułu PWA).
const UPDATE_READY_EVENT = "pwa:update-ready";

const isOnline = () => (typeof navigator === "undefined" ? true : navigator.onLine !== false);

/**
 * Paski stanu aplikacji na dole ekranu: brak internetu (dane z API wtedy nie przyjdą) i nowa wersja aplikacji
 * do włączenia (PWA trzyma pliki aplikacji w pamięci telefonu, więc nowa wersja czeka na odświeżenie).
 */
function AppStatusBanner() {
  const [online, setOnline] = useState(isOnline);
  const [update, setUpdate] = useState(null);

  useEffect(() => {
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    const onUpdate = (event) => setUpdate(() => event.detail.update);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener(UPDATE_READY_EVENT, onUpdate);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener(UPDATE_READY_EVENT, onUpdate);
    };
  }, []);

  if (online && !update) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      {!online && (
        <p role="status" className="pointer-events-auto flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm text-white shadow-lg">
          <FiWifiOff aria-hidden="true" /> Brak połączenia z internetem. Dane odświeżą się po jego powrocie.
        </p>
      )}
      {update && (
        <div role="status" className="pointer-events-auto flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-800 shadow-lg">
          <span>Jest nowa wersja aplikacji.</span>
          <button type="button" className={buttonClass("primary", "sm")} onClick={() => update()}>
            <FiRefreshCw aria-hidden="true" /> Odśwież
          </button>
        </div>
      )}
    </div>
  );
}

export default AppStatusBanner;
