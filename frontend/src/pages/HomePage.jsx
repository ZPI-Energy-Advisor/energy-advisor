import { useState } from "react";
import { Navigate } from "react-router-dom";
import apiClient from "../api/client";
import HomeConnectionPanel from "../components/HomeConnectionPanel";
import SegmentedControl from "../components/SegmentedControl";
import HomeDeviceList from "../components/home/HomeDeviceList";
import HomeSummary from "../components/home/HomeSummary";
import LivePanel from "../components/home/LivePanel";
import HouseView from "../components/home/HouseView";
import PlanRunBar from "../components/home/PlanRunBar";
import { DeviationList } from "../components/home/PlanRunCost";
import PlanRunHistory from "../components/home/PlanRunHistory";
import SimulationClock from "../components/home/SimulationClock";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useHomeState } from "../hooks/useHomeState";
import { useSimulationWeather } from "../hooks/useSimulationWeather";
import { usePlanRun } from "../hooks/usePlanRun";
import { getApiErrorMessage } from "../utils/energyFiles";
import { planBadges, planName } from "../utils/home";

const NOTICE = "p-3 rounded border text-sm";
const ERROR_NOTICE = `${NOTICE} border-red-200 bg-red-50 text-red-700`;

const VIEW_OPTIONS = [
  { value: "house", label: "Dom" },
  { value: "list", label: "Lista" },
];

// Stan i sterowanie podłączonego domu. Montowany tylko przy podłączonym domu, więc odłączenie
// kończy odpytywanie i czyści stan, a ponowne podłączenie zaczyna od świeżego pobrania.
function HomeLive({ onShowReport }) {
  const { state, error, isLoading, refresh } = useHomeState();
  const [actionError, setActionError] = useState(null);
  const [view, setView] = useState("house");
  const planRun = usePlanRun(state?.clock?.sim_time, state?.simulation_id);
  const weather = useSimulationWeather(state?.clock?.sim_time);

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

  // Odpowiedź „Zakończ” to już zamknięty przebieg, więc podmieniamy kartę bez kolejnego żądania.
  const endPlanRun = (run) =>
    perform(
      async () => planRun.replace((await apiClient.post(`/home/plan-runs/${run.id}/end`)).data),
      (err) => getApiErrorMessage(err, "Nie udało się zakończyć przebiegu planu."),
    );

  // Ten sam plan jeszcze raz od północy jego doby; odpowiedź to już nowy przebieg.
  const restartPlanRun = (run) =>
    perform(
      async () => planRun.replace((await apiClient.post("/home/plan-runs", { plan_id: run.plan_id })).data),
      (err) => getApiErrorMessage(err, "Nie udało się uruchomić planu ponownie."),
    );

  const hubDown = state?.hub_available === false;
  const running = planRun.run?.status === "running";
  // Po końcu planu ta symulacja nie ma już nic do zrobienia: zegar szedłby dalej bez planu i bez PV.
  // Inna symulacja (np. hub po restarcie) nie jest blokowana.
  const finishedHere =
    planRun.run && !running && planRun.run.simulation_id === state?.simulation_id;
  const startBlocked = finishedHere
    ? `${planName(planRun.run)} się skończył. Żeby go powtórzyć, kliknij „Uruchom ponownie”.`
    : null;
  // Urządzenia sterujemy tylko przy chodzącym zegarze: w pauzie i po końcu planu włączenie niczego by nie
  // policzyło (zegar stoi), a po końcu planu psułoby stan, który widać w raporcie.
  const controlsLocked = !state?.clock?.running;
  const lockedNote = finishedHere
    ? "Plan się skończył, więc urządzeń już nie włączysz. Żeby symulować dalej, kliknij „Uruchom ponownie”."
    : "Symulacja jest zatrzymana. Urządzenia włączysz po kliknięciu „Start”.";
  // Odchylenia z rachunku; przebieg bez rachunku (sprzed ZP-114 albo jeszcze bez zdarzeń) ma tylko awarie.
  const deviations = planRun.run?.cost
    ? planRun.run.cost.deviations
    : (planRun.run?.errors ?? []).map((error) => ({ ...error, kind: "device_error", end: null, excluded: false }));

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
          <SimulationClock
            clock={state.clock}
            disabled={hubDown}
            onUpdate={updateClock}
            startBlocked={startBlocked}
            weather={weather}
            plan={planRun.run && (
              <PlanRunBar
                run={planRun.run}
                disabled={hubDown}
                onEnd={endPlanRun}
                onRestart={restartPlanRun}
                onShowReport={onShowReport}
              />
            )}
          />
          {running && deviations.length > 0 && (
            <section
              className={`${NOTICE} border-amber-200 bg-amber-50 text-amber-900`}
              role="alert"
              aria-label="Odchylenia od planu"
            >
              <DeviationList deviations={deviations} />
            </section>
          )}
          {planRun.error && (
            <p className={ERROR_NOTICE} role="alert">
              {planRun.error}
            </p>
          )}
          <HomeSummary power={state.power} today={state.today} />
          {!hubDown && (
            <LivePanel
              live={running && planRun.run.simulation_id === state.simulation_id ? planRun.run.live : null}
              weather={weather}
              today={state.today}
            />
          )}
          {!hubDown && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-gray-600" role="status">
                  {controlsLocked ? lockedNote : ""}
                </p>
                <SegmentedControl label="Widok urządzeń" options={VIEW_OPTIONS} value={view} onChange={setView} />
              </div>
              {view === "house" ? (
                <HouseView
                  devices={state.devices}
                  power={state.power}
                  simTime={state.clock?.sim_time}
                  onCommand={sendCommand}
                  disabled={controlsLocked}
                  planBadges={planBadges(planRun.run)}
                  // Pasek czasu i wskaźniki tylko z przebiegu tej symulacji, nie z planu sprzed restartu huba.
                  planRun={planRun.run?.simulation_id === state.simulation_id ? planRun.run : null}
                />
              ) : (
                <HomeDeviceList
                  devices={state.devices}
                  onCommand={sendCommand}
                  disabled={controlsLocked}
                  planBadges={planBadges(planRun.run)}
                />
              )}
            </>
          )}
        </>
      )}
    </>
  );
}

const TABS = [
  { id: "simulation", label: "Symulacja" },
  { id: "reports", label: "Raporty" },
];

// Ekran „Mój dom”: zakładka „Symulacja” (podłączenie domu, zegar, bilans i urządzenia z huba Smart Home)
// i „Raporty” z poprzednich przebiegów planu, dostępne bez działającej symulacji.
// Tylko dla właściciela domu (HUB_HOME_USER_EMAIL); pozostałe konta wracają na dashboard.
function HomePage() {
  const { me, isReady, loadError } = useCurrentUser();
  const [connection, setConnection] = useState(null);
  const [tab, setTab] = useState("simulation");
  // Raport do otwarcia po „Zobacz raport”. Ręczne przełączenie zakładki go czyści, żeby „Raporty” nie
  // otwierały wciąż tego samego raportu.
  const [reportToOpen, setReportToOpen] = useState(null);
  const showReport = (run) => {
    setReportToOpen(run.id);
    setTab("reports");
  };
  const switchTab = (id) => {
    setReportToOpen(null);
    setTab(id);
  };

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

      <div className="flex gap-1 border-b border-gray-200" role="tablist" aria-label="Mój dom">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => switchTab(item.id)}
            className={`px-4 py-2 -mb-px border-b-2 text-sm font-medium ${
              tab === item.id
                ? "border-emerald-600 text-emerald-700"
                : "border-transparent text-gray-600 hover:text-gray-900"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Zakładka symulacji zostaje zamontowana (ukryta), żeby podłączenie domu nie pytało API od nowa
          przy każdym przełączeniu; raporty pobierają się przy otwarciu zakładki. */}
      <div className="space-y-6" hidden={tab !== "simulation"}>
        <HomeConnectionPanel onStatusChange={setConnection} />
        {connection?.connected && <HomeLive onShowReport={showReport} />}
      </div>
      {tab === "reports" && <PlanRunHistory openId={reportToOpen} />}
    </div>
  );
}

export default HomePage;
