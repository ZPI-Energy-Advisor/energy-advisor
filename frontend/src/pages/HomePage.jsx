import { useState } from "react";
import { Navigate } from "react-router-dom";
import apiClient from "../api/client";
import HomeConnectionPanel from "../components/HomeConnectionPanel";
import HomeDeviceList from "../components/home/HomeDeviceList";
import HomeSummary from "../components/home/HomeSummary";
import SimulationClock from "../components/home/SimulationClock";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useHomeState } from "../hooks/useHomeState";
import { getApiErrorMessage } from "../utils/energyFiles";

const NOTICE = "p-3 rounded border text-sm";
const ERROR_NOTICE = `${NOTICE} border-red-200 bg-red-50 text-red-700`;

// Stan i sterowanie podłączonego domu. Montowany tylko przy podłączonym domu, więc odłączenie
// kończy odpytywanie i czyści stan, a ponowne podłączenie zaczyna od świeżego pobrania.
function HomeLive() {
  const { state, error, isLoading, refresh } = useHomeState();
  const [actionError, setActionError] = useState(null);

  // Polecenie zmienia stan w hubie, więc po nim (także nieudanym) od razu pobieramy stan domu.
  const perform = async (request, describeError) => {
    try {
      await request();
      setActionError(null);
      return true;
    } catch (err) {
      setActionError(describeError(err));
      return false;
    } finally {
      refresh();
    }
  };

  const sendCommand = (device, command) =>
    perform(
      () => apiClient.post(`/home/devices/${encodeURIComponent(device.device_id)}/commands`, command),
      (err) => `${device.device_name}: ${getApiErrorMessage(err, "nie udało się wysłać polecenia.")}`,
    );

  const updateClock = (change) =>
    perform(
      () => apiClient.put("/home/clock", change),
      (err) => getApiErrorMessage(err, "Nie udało się zmienić zegara symulacji."),
    );

  const hubDown = state?.hub_available === false;

  return (
    <>
      {isLoading && (
        <p className="text-sm text-gray-500" role="status">
          Ładowanie stanu domu…
        </p>
      )}

      {error && (
        <p className={ERROR_NOTICE} role="alert">
          {state ? `Nie udało się odświeżyć stanu: ${error}` : error}{" "}
          <button type="button" onClick={refresh} className="font-semibold underline">
            Spróbuj ponownie
          </button>
        </p>
      )}

      {hubDown && (
        <p className={`${NOTICE} border-amber-200 bg-amber-50 text-amber-800`} role="status">
          Hub Smart Home nie odpowiada. Zużycie pochodzi z ostatnich zapisanych zdarzeń, a sterowanie wróci,
          gdy hub będzie dostępny.
        </p>
      )}

      {actionError && (
        <p className={ERROR_NOTICE} role="alert">
          {actionError}
        </p>
      )}

      {state && (
        <>
          <SimulationClock clock={state.clock} disabled={hubDown} onUpdate={updateClock} />
          <HomeSummary power={state.power} today={state.today} />
          {!hubDown && <HomeDeviceList devices={state.devices} onCommand={sendCommand} />}
        </>
      )}
    </>
  );
}

// Ekran „Mój dom”: podłączenie domu, zegar symulacji, bilans i urządzenia z huba Smart Home.
// Tylko dla właściciela domu (HUB_HOME_USER_EMAIL); pozostałe konta wracają na dashboard.
function HomePage() {
  const { me, isReady, loadError } = useCurrentUser();
  const [connection, setConnection] = useState(null);

  if (!isReady) {
    return (
      <p className="text-sm text-gray-500" role="status">
        Ładowanie…
      </p>
    );
  }
  if (!me) {
    return (
      <p className={ERROR_NOTICE} role="alert">
        {loadError}
      </p>
    );
  }
  if (!me.home_owner) return <Navigate to="/dashboard" replace />;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="border-b border-gray-200 pb-4">
        <h2 className="text-xl font-bold text-gray-900">Mój dom</h2>
        <p className="text-sm text-gray-600 mt-1">Symulacja urządzeń z Twoich plików: co pracuje, ile zużywa i ile kosztuje.</p>
      </div>

      <HomeConnectionPanel onStatusChange={setConnection} />

      {connection?.connected && <HomeLive />}
    </div>
  );
}

export default HomePage;
